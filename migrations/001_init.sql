-- Migration 001: Initial Schema
-- Governing spec: BE-02 §4

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        CREATE EXTENSION IF NOT EXISTS vector;
    ELSE
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'halfvec') THEN
            CREATE DOMAIN halfvec AS text;
        END IF;
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TYPE document_status AS ENUM (
    'pending',      -- accepted, queued
    'extracting',   -- BE-04 running
    'chunking',     -- BE-05 running
    'embedding',    -- BE-06 running
    'ready',        -- queryable
    'failed'        -- terminal; see status_detail
);

CREATE TYPE query_outcome AS ENUM (
    'answered',
    'insufficient_context',
    'error'
);

CREATE TABLE schema_version (
    version     integer     PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    description text        NOT NULL
);

CREATE TABLE document (
    id            uuid            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Ownership: '__demo__', 'session:<uuid>', or 'user:<uuid>'
    owner_key     text            NOT NULL,

    -- Identity
    sha256        text            NOT NULL,
    filename      text            NOT NULL,
    title         text            NOT NULL,
    mime          text            NOT NULL,
    byte_size     bigint          NOT NULL,
    storage_path  text            NOT NULL,

    -- Extraction results (NULL until extraction completes)
    page_count    integer,
    char_count    integer,
    chunk_count   integer,

    -- Lifecycle
    status        document_status NOT NULL DEFAULT 'pending',
    status_detail text,
    error_code    text,

    created_at    timestamptz     NOT NULL DEFAULT now(),
    updated_at    timestamptz     NOT NULL DEFAULT now(),
    ready_at      timestamptz,

    CONSTRAINT document_owner_sha_unique UNIQUE (owner_key, sha256),
    CONSTRAINT document_mime_allowed CHECK (mime IN (
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )),
    CONSTRAINT document_byte_size_positive CHECK (byte_size > 0),
    CONSTRAINT document_failed_has_detail CHECK (
        status <> 'failed' OR status_detail IS NOT NULL
    ),
    CONSTRAINT document_ready_has_chunks CHECK (
        status <> 'ready' OR (chunk_count IS NOT NULL AND chunk_count > 0)
    )
);

CREATE INDEX document_owner_created_idx ON document (owner_key, created_at DESC);
CREATE INDEX document_status_idx        ON document (status) WHERE status <> 'ready';

CREATE TABLE chunk (
    id              bigserial   PRIMARY KEY,
    document_id     uuid        NOT NULL REFERENCES document(id) ON DELETE CASCADE,

    -- Denormalized from document for single-statement retrieval (BE-01-R12)
    owner_key       text        NOT NULL,

    -- Position
    ordinal         integer     NOT NULL,
    page_from       integer,
    page_to         integer,
    section_path    text,
    char_start      integer     NOT NULL,
    char_end        integer     NOT NULL,

    -- Content
    content         text        NOT NULL,
    token_count     integer     NOT NULL,
    content_tsv     tsvector    GENERATED ALWAYS AS (
                        to_tsvector('english', content)
                    ) STORED,

    -- Vector (768 dimensions halfvec)
    embedding       halfvec(768),
    embedding_model text,

    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT chunk_document_ordinal_unique UNIQUE (document_id, ordinal),
    CONSTRAINT chunk_content_not_empty  CHECK (length(trim(content)) > 0),
    CONSTRAINT chunk_token_count_sane   CHECK (token_count BETWEEN 1 AND 2000),
    CONSTRAINT chunk_offsets_ordered    CHECK (char_end > char_start),
    CONSTRAINT chunk_pages_ordered      CHECK (page_to IS NULL OR page_from IS NULL
                                               OR page_to >= page_from),
    CONSTRAINT chunk_embedding_has_model CHECK (
        (embedding IS NULL) = (embedding_model IS NULL)
    )
);

-- Vector leg (BE-08). Cosine distance (when vector extension is available).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw_idx ON chunk
            USING hnsw (embedding halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64);
    END IF;
END $$;

-- Keyword leg (BE-08).
CREATE INDEX chunk_content_tsv_idx ON chunk USING gin (content_tsv);

-- Ownership filter, applied before ANN search.
CREATE INDEX chunk_owner_idx ON chunk (owner_key);

-- Citation resolution: fetch chunks by id with their document metadata.
CREATE INDEX chunk_document_idx ON chunk (document_id);

CREATE TABLE query_log (
    id                  uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key           text          NOT NULL,

    question            text          NOT NULL,
    scope               text          NOT NULL,
    document_ids        uuid[],

    outcome             query_outcome NOT NULL,

    -- Gate (BE-11)
    top_similarity      real,
    supporting_count    integer,
    gate_passed         boolean       NOT NULL,
    gate_reason         text,

    -- Retrieval detail
    retrieval           jsonb         NOT NULL DEFAULT '[]'::jsonb,

    -- Validated answer payload (BE-12)
    answer              jsonb,

    -- Validation (BE-10)
    validation_attempts integer       NOT NULL DEFAULT 0,
    validation_errors   jsonb,

    -- Observability
    timings_ms          jsonb         NOT NULL DEFAULT '{}'::jsonb,
    embedding_model     text,
    generation_model    text,
    error_code          text,

    created_at          timestamptz   NOT NULL DEFAULT now()
);

CREATE INDEX query_log_owner_created_idx ON query_log (owner_key, created_at DESC);
CREATE INDEX query_log_outcome_idx       ON query_log (outcome, created_at DESC);

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER document_touch_updated_at
    BEFORE UPDATE ON document
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- BE-02-R1: Every migration MUST insert exactly one row in schema_version
INSERT INTO schema_version (version, description)
VALUES (1, 'Initial schema: document, chunk, query_log with halfvec(768) and HNSW index');
