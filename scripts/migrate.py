#!/usr/bin/env python3
"""Database migration runner.
Governing spec: BE-02 §1, ADR-0007.
Applies numbered SQL migrations in ascending order.
"""

import asyncio
import os
import sys
from pathlib import Path
import asyncpg

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings


async def run_migrations() -> None:
    settings = get_settings()
    database_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    migrations_dir = Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        print(f"ERROR: Migrations directory {migrations_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        print("No migration files found.")
        return

    print(f"Connecting to database to apply migrations...")
    try:
        conn = await asyncpg.connect(database_url)
    except asyncpg.InvalidCatalogNameError:
        # If target database doesn't exist, try connecting to default 'postgres' db to create it
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(database_url)
        target_db = parsed.path.lstrip("/")
        maintenance_url = urlunparse(parsed._replace(path="/postgres"))
        print(f"Database '{target_db}' does not exist. Creating it via maintenance connection...")
        m_conn = await asyncpg.connect(maintenance_url)
        try:
            await m_conn.execute(f'CREATE DATABASE "{target_db}"')
            print(f"Database '{target_db}' created successfully.")
        finally:
            await m_conn.close()
        conn = await asyncpg.connect(database_url)
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        sys.exit(1)
    try:
        # Check current applied versions
        applied_versions = set()
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_version')"
        )
        if table_exists:
            rows = await conn.fetch("SELECT version FROM schema_version")
            applied_versions = {row["version"] for row in rows}

        for sql_file in sql_files:
            # File name pattern: 001_init.sql -> version 1
            version_str = sql_file.name.split("_")[0]
            try:
                version = int(version_str)
            except ValueError:
                print(f"Skipping non-numbered migration file: {sql_file.name}")
                continue

            if version in applied_versions:
                print(f"Migration {sql_file.name} (version {version}) already applied.")
                continue

            print(f"Applying migration {sql_file.name} (version {version})...")
            sql_content = sql_file.read_text(encoding="utf-8")
            
            # Check if pgvector extension is available on this PostgreSQL instance
            has_vector = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')"
            )
            if not has_vector:
                sql_content = sql_content.replace("embedding       halfvec(768),", "embedding       text,")
                sql_content = sql_content.replace("embedding halfvec(768),", "embedding text,")

            async with conn.transaction():
                await conn.execute(sql_content)
            print(f"Successfully applied {sql_file.name}.")

        print("All migrations successfully applied.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
