import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/verity_db')
    try:
        has_vector = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
        print("pgvector available:", has_vector)
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
