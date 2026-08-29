"""Ingestion pipeline orchestrating extraction, chunking, embedding, and storage.
Governing specs: BE-03, BE-04, BE-05, BE-06, BE-07.
"""

from typing import List, Tuple
from uuid import UUID
import asyncpg

from app.core.config import Settings
from app.core.errors import (
    AppError,
    PipelineError,
    IncompleteEmbeddingError,
)
from app.core.logging import logger
from app.db.documents import (
    get_document_by_id,
    update_document_status,
    update_document_extraction,
)
from app.db.chunks import (
    insert_chunks,
    set_embeddings,
    count_unembedded,
    delete_chunks,
)
from app.storage.supabase import get_object
from app.ingestion.extract_pdf import extract_pdf
from app.ingestion.extract_docx import extract_docx
from app.ingestion.chunk import chunk_document
from app.embedding.client import GeminiEmbeddingClient, format_halfvec_literal
from app.models.documents import DocumentStatus


async def ingest_document(
    document_id: UUID,
    pool: asyncpg.Pool,
    settings: Settings,
) -> None:
    """Execute the asynchronous ingestion pipeline for a document."""
    logger.info(f"Starting ingestion pipeline for document {document_id}")

    # Fetch document record
    doc_tuple = await get_document_by_id(pool, document_id)
    if not doc_tuple:
        logger.warning(f"Document {document_id} was deleted before ingestion started.")
        return

    doc_out, storage_path, owner_key = doc_tuple

    try:
        # Step 1: Fetch file bytes from storage
        file_bytes = await get_object(storage_path, settings)

        # Step 2: Extraction (status -> extracting)
        await update_document_status(pool, document_id, DocumentStatus.EXTRACTING)
        if doc_out.mime == "application/pdf":
            extracted_doc = extract_pdf(file_bytes, doc_out.filename, settings)
        else:
            extracted_doc = extract_docx(file_bytes, doc_out.filename, settings)

        # Step 3: Chunking (status -> chunking)
        await update_document_status(pool, document_id, DocumentStatus.CHUNKING)
        prepared_chunks = chunk_document(extracted_doc, settings)

        # Record extraction metadata
        await update_document_extraction(
            pool,
            document_id,
            page_count=extracted_doc.page_count,
            char_count=len(extracted_doc.text),
            chunk_count=len(prepared_chunks),
            title=extracted_doc.title or doc_out.title,
        )

        # Step 4: Storage Phase 1 (Clean existing chunks and single-statement chunk insert)
        await delete_chunks(pool, document_id)
        chunk_ids = await insert_chunks(pool, document_id, owner_key, prepared_chunks)

        # Step 5: Storage Phase 2 (status -> embedding)
        await update_document_status(pool, document_id, DocumentStatus.EMBEDDING)
        embedding_client = GeminiEmbeddingClient(settings)
        batch_size = settings.EMBEDDING_BATCH_SIZE

        import asyncio

        for i in range(0, len(prepared_chunks), batch_size):
            chunk_batch = prepared_chunks[i : i + batch_size]
            id_batch = chunk_ids[i : i + batch_size]

            # BE-05-R13: Embedding input contains section_path prefix
            texts_to_embed = [c.embedding_input for c in chunk_batch]
            vectors = await embedding_client.embed_documents(texts_to_embed)

            update_rows: List[Tuple[int, str, str]] = []
            for chunk_id, vec in zip(id_batch, vectors):
                update_rows.append((
                    chunk_id,
                    format_halfvec_literal(vec),
                    settings.EMBEDDING_MODEL,
                ))

            await set_embeddings(pool, update_rows, dimension=settings.EMBEDDING_DIMENSIONS)

            # Pacing delay between multi-batch document chunks to prevent rate limits
            if i + batch_size < len(prepared_chunks):
                pacing_delay = max(0.5, 60.0 / max(1, settings.GEMINI_RPM))
                await asyncio.sleep(pacing_delay)

        # Step 6: Verification before ready (BE-07-R8)
        unembedded_count = await count_unembedded(pool, document_id)
        if unembedded_count > 0:
            raise IncompleteEmbeddingError()

        # Step 7: Ready
        await update_document_status(pool, document_id, DocumentStatus.READY)
        logger.info(f"Document {document_id} successfully indexed into {len(prepared_chunks)} chunks.")

    except PipelineError as pe:
        logger.error(f"Ingestion pipeline error for document {document_id}: {pe.code} - {pe.status_detail}")
        await delete_chunks(pool, document_id)
        await update_document_status(
            pool,
            document_id,
            DocumentStatus.FAILED,
            status_detail=pe.status_detail,
            error_code=pe.code,
        )
    except AppError as ae:
        logger.error(f"Ingestion AppError for document {document_id}: {ae.code} - {ae.message}")
        await delete_chunks(pool, document_id)
        await update_document_status(
            pool,
            document_id,
            DocumentStatus.FAILED,
            status_detail=ae.message,
            error_code=ae.code,
        )
    except Exception as e:
        logger.exception(f"Unexpected error ingesting document {document_id}: {e}")
        await delete_chunks(pool, document_id)
        await update_document_status(
            pool,
            document_id,
            DocumentStatus.FAILED,
            status_detail="Processing failed while indexing this document.",
            error_code="INTERNAL_ERROR",
        )
