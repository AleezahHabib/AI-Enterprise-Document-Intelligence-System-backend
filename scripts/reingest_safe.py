import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
import uuid
from app.core.config import get_settings
from app.ingestion.pipeline import ingest_document

async def run():
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    doc_id = uuid.UUID("b7fca89b-deda-43d3-9772-e62b986c23e8")
    print(f"Starting reliable ingestion for document {doc_id}...")
    await ingest_document(doc_id, pool, settings)
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, filename, status, status_detail, chunk_count, page_count FROM document WHERE id = $1",
            doc_id,
        )
        print("Final Document State:", dict(row))
    await pool.close()

if __name__ == "__main__":
    asyncio.run(run())
