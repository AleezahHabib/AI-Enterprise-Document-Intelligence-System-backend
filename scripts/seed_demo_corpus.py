"""Seed the curated public demo corpus.
Governing spec: BE-17 §3, BE-07-R16.
"""

import asyncio
import hashlib
import os
import sys
import uuid
from pathlib import Path
from typing import List, Tuple
import asyncpg

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings, get_settings
from app.ingestion.extract_pdf import extract_pdf
from app.ingestion.extract_docx import extract_docx
from app.ingestion.chunk import chunk_document
from app.embedding.client import GeminiEmbeddingClient, format_halfvec_literal
from app.db.documents import create_document, get_document_by_sha256, update_document_extraction, update_document_status
from app.db.chunks import insert_chunks, set_embeddings, count_unembedded
from app.models.documents import DocumentStatus
from app.storage.supabase import put_object


async def seed_demo():
    settings = get_settings()
    if not settings.DATABASE_URL:
        print("DATABASE_URL is required to seed the demo corpus.", file=sys.stderr)
        sys.exit(1)

    demo_dir = Path(__file__).parent.parent / "data" / "demo_corpus"
    if not demo_dir.exists():
        print(f"Demo corpus directory {demo_dir} not found.", file=sys.stderr)
        sys.exit(1)

    files = list(demo_dir.glob("*.pdf")) + list(demo_dir.glob("*.docx"))
    if not files:
        print("No demo files found to seed.")
        return

    print(f"Connecting to database to seed {len(files)} demo files...")
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=3,
        statement_cache_size=settings.DB_STATEMENT_CACHE_SIZE,
    )

    owner_key = "__demo__"
    embedding_client = GeminiEmbeddingClient(settings)

    try:
        for file_path in files:
            file_bytes = file_path.read_bytes()
            sha256 = hashlib.sha256(file_bytes).hexdigest()
            filename = file_path.name
            mime = "application/pdf" if filename.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            existing = await get_document_by_sha256(pool, owner_key, sha256)
            if existing and existing.status == DocumentStatus.READY:
                print(f"Demo file {filename} already indexed. Skipping.")
                continue

            print(f"Seeding demo document: {filename}...")
            doc_id = uuid.uuid4()
            storage_path = f"demo/{doc_id}/{filename}"
            await put_object(storage_path, file_bytes, mime, settings)

            # Extract
            if mime == "application/pdf":
                extracted = extract_pdf(file_bytes, filename, settings)
            else:
                extracted = extract_docx(file_bytes, filename, settings)

            # Chunk
            prepared_chunks = chunk_document(extracted, settings)

            # Insert document
            doc_out = await create_document(
                pool=pool,
                document_id=doc_id,
                owner_key=owner_key,
                sha256=sha256,
                filename=filename,
                title=extracted.title or filename.rsplit(".", 1)[0],
                mime=mime,
                byte_size=len(file_bytes),
                storage_path=storage_path,
            )

            await update_document_extraction(
                pool=pool,
                document_id=doc_id,
                page_count=extracted.page_count,
                char_count=len(extracted.text),
                chunk_count=len(prepared_chunks),
                title=extracted.title or filename.rsplit(".", 1)[0],
            )

            # Insert chunks (Phase 1)
            chunk_ids = await insert_chunks(pool, doc_id, owner_key, prepared_chunks)

            # Embed chunks (Phase 2)
            for i in range(0, len(prepared_chunks), settings.EMBEDDING_BATCH_SIZE):
                chunk_batch = prepared_chunks[i : i + settings.EMBEDDING_BATCH_SIZE]
                id_batch = chunk_ids[i : i + settings.EMBEDDING_BATCH_SIZE]

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

            # Verify
            unembedded = await count_unembedded(pool, doc_id)
            if unembedded == 0:
                await update_document_status(pool, doc_id, DocumentStatus.READY)
                print(f"Successfully seeded {filename} ({len(prepared_chunks)} chunks).")
            else:
                print(f"ERROR: {unembedded} chunks remained unembedded for {filename}.")

        # BE-07-R16: Run ANALYZE chunk post-seed
        async with pool.acquire() as conn:
            await conn.execute("ANALYZE chunk;")
            await conn.execute("ANALYZE document;")
        print("Planner statistics updated (ANALYZE chunk complete).")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(seed_demo())
