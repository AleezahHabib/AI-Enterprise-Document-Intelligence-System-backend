import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import asyncpg
import httpx
from app.core.config import get_settings
from app.db.pool import init_pool, close_pool
from app.main import app

async def main():
    settings = get_settings()
    await init_pool(settings)
    conn = await asyncpg.connect(settings.DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT id, owner_key, title, status, chunk_count FROM document WHERE title ILIKE '%Open Book%' AND status = 'ready' ORDER BY created_at DESC LIMIT 1"
    )
    await conn.close()
    
    if not row:
        print("Error: No ready OBCM document found in database.")
        await close_pool()
        return

    print("Target OBCM Document:", dict(row))
    owner = row["owner_key"]
    session_id = owner.split(":", 1)[1] if ":" in owner else owner
    doc_id = str(row["id"])
    
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=35.0) as client:
            print("\n--- TEST 1: Question with scope='mine' (User's uploaded OBCM document) ---")
            payload1 = {
                "question": "Who is the Open Book Contract Management guidance intended for?",
                "scope": "mine",
                "include_retrieval": True,
            }
            res1 = await client.post("/api/v1/query", headers={"X-Session-Id": session_id}, json=payload1)
            d1 = res1.json()
            print("Status:", d1.get("status"))
            print("Answer:", d1.get("answer"))
            for claim in d1.get("claims") or []:
                for cit in claim.get("citations") or []:
                    page = cit.get("page")
                    print(f"  * [{cit.get('document_title')}] (page {page}): {cit.get('quote')[:70]}...")
            assert d1.get("status") == "answered", f"Expected answered, got {d1.get('status')}"
            
            print("\n--- TEST 2: Question with scope='all' and document_ids filter ---")
            payload2 = {
                "question": "Who is the Open Book Contract Management guidance intended for?",
                "scope": "all",
                "document_ids": [doc_id],
                "include_retrieval": True,
            }
            res2 = await client.post("/api/v1/query", headers={"X-Session-Id": session_id}, json=payload2)
            d2 = res2.json()
            print("Status:", d2.get("status"))
            print("Answer:", d2.get("answer"))
            for claim in d2.get("claims") or []:
                for cit in claim.get("citations") or []:
                    page = cit.get("page")
                    print(f"  * [{cit.get('document_title')}] (page {page}): {cit.get('quote')[:70]}...")
                    assert cit.get("document_id") == doc_id
            assert d2.get("status") == "answered"

            print("\n--- TEST 3: OBCM Question on Demo Scope only (where OBCM is NOT present) ---")
            payload3 = {
                "question": "Who is the Open Book Contract Management guidance intended for?",
                "scope": "demo",
                "include_retrieval": True,
            }
            res3 = await client.post("/api/v1/query", headers={"X-Session-Id": session_id}, json=payload3)
            d3 = res3.json()
            print("Status:", d3.get("status"))
            print("Refusal Reason:", d3.get("refusal", {}).get("reason") if d3.get("refusal") else None)
            print("Refusal Message:", d3.get("refusal", {}).get("message") if d3.get("refusal") else None)
            print("Nearest Docs:", [(doc["document_title"], doc["top_similarity"]) for doc in (d3.get("refusal", {}).get("nearest_documents") or [])])
            assert d3.get("status") == "insufficient_context"
            assert d3.get("refusal") is not None

            print("\n==========================================")
            print(">>> ALL RAG GROUNDING TESTS PASSED! <<<")
            print("==========================================")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())


