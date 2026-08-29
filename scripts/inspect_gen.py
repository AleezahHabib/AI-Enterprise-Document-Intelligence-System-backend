import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from app.core.config import get_settings
from app.retrieval.hybrid import retrieve_chunks
from app.retrieval.gate import evaluate_gate
from app.models.documents import Scope
from app.generation.prompt import build_user_prompt, SYSTEM_INSTRUCTION
from google import genai
from google.genai import types
from app.models.queries import RawGenerationOut

async def inspect_gen():
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    
    question = "Who is the Open Book Contract Management guidance intended for?"
    scope = Scope.MINE
    caller_owner_key = "session:cf87f34d-b882-4c0e-90a9-04b67e6bdb72"
    
    retrieval_res = await retrieve_chunks(
        question=question,
        scope=scope,
        caller_owner_key=caller_owner_key,
        document_ids=None,
        pool=pool,
        settings=settings,
    )
    
    context_chunks = [c for c in retrieval_res.chunks if c.used_in_context]
    print(f"Context chunks count: {len(context_chunks)}")
    # context chunks info
        
    user_prompt = build_user_prompt(question, context_chunks)
    
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=RawGenerationOut,
        temperature=settings.GENERATION_TEMPERATURE,
    )
    
    response = client.models.generate_content(
        model=settings.GENERATION_MODEL,
        contents=[user_prompt],
        config=config,
    )
    
    with open("raw_gen_output.txt", "w", encoding="utf-8") as f:
        f.write(f"Raw Text:\n{response.text}\n\nParsed:\n{response.parsed}\n")
    print("Done generating. Saved to raw_gen_output.txt")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(inspect_gen())
