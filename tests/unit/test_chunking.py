"""Unit tests for BE-05 Structure-Aware Chunking.
Named by requirement IDs per BE-16-R4.
"""

import pytest
from app.core.config import Settings
from app.models.extraction import ExtractedBlock, ExtractedDocument
from app.ingestion.chunk import chunk_document, split_into_sentences


def get_test_settings():
    return Settings(
        DATABASE_URL="postgresql://postgres:test@localhost:5432/test",
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_SERVICE_KEY="test_key",
        GEMINI_API_KEY="test_key",
        CHUNK_TARGET_TOKENS=100,
        CHUNK_MAX_TOKENS=250,
        CHUNK_OVERLAP_TOKENS=20,
        CHUNK_MIN_TOKENS=30,
        MIN_CHARS_PER_CHUNK=20,
    )


def test_be_05_r9_sentence_splitting_with_abbreviations():
    """BE-05-R9: Sentence splitting protects abbreviations like Inc., e.g., and decimals 3.2."""
    text = "ACME Global Inc. was founded in 2020. See Section 3.2 for details. The SLA is 99.95% uptime."
    sentences = split_into_sentences(text)
    assert len(sentences) == 3
    assert sentences[0] == "ACME Global Inc. was founded in 2020."
    assert sentences[1] == "See Section 3.2 for details."
    assert sentences[2] == "The SLA is 99.95% uptime."


def test_be_05_r10_section_path_hierarchy_tracked():
    """BE-05-R10: Section hierarchy tracked and joined with ' > '."""
    settings = get_test_settings()
    blocks = [
        ExtractedBlock(text="3. Retention Policy", page=1, char_start=0, char_end=19, heading_level=1, bbox=None),
        ExtractedBlock(text="3.1 Customer Data", page=1, char_start=21, char_end=38, heading_level=2, bbox=None),
        ExtractedBlock(
            text="Customer records must be retained for seven years following account closure.",
            page=1, char_start=40, char_end=115, heading_level=None, bbox=None
        ),
    ]
    doc = ExtractedDocument(text="...", blocks=blocks, page_count=1, title="Test")
    chunks = chunk_document(doc, settings)

    assert len(chunks) >= 1
    assert chunks[0].section_path == "3. Retention Policy > 3.1 Customer Data"


def test_be_05_r13_section_path_in_embedding_input_only_never_in_content():
    """BE-05-R13: Section path prefix is added ONLY to embedding_input and NEVER to chunk.content."""
    settings = get_test_settings()
    blocks = [
        ExtractedBlock(text="Security Standard", page=1, char_start=0, char_end=17, heading_level=1, bbox=None),
        ExtractedBlock(
            text="All database connections must use TLS 1.3 cryptographic protocols.",
            page=1, char_start=19, char_end=85, heading_level=None, bbox=None
        ),
    ]
    doc = ExtractedDocument(text="...", blocks=blocks, page_count=1, title="Test")
    chunks = chunk_document(doc, settings)

    assert len(chunks) == 1
    chunk = chunks[0]

    # Stored content must be strictly the verbatim text
    assert chunk.content == "All database connections must use TLS 1.3 cryptographic protocols."
    assert "Security Standard" not in chunk.content

    # Embedding input must contain the section prefix
    assert chunk.embedding_input == "Security Standard\n\nAll database connections must use TLS 1.3 cryptographic protocols."
    assert "Security Standard" in chunk.embedding_input
