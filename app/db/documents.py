"""Database queries for document CRUD and status transitions.
Governing spec: BE-02, BE-03, BE-12.
"""

from typing import List, Optional, Tuple
from uuid import UUID
import asyncpg
from app.models.documents import DocumentOut, DocumentStatus, Scope


async def create_document(
    pool: asyncpg.Pool,
    document_id: UUID,
    owner_key: str,
    sha256: str,
    filename: str,
    title: str,
    mime: str,
    byte_size: int,
    storage_path: str,
) -> DocumentOut:
    """Insert a new document row in 'pending' status."""
    is_demo = owner_key == "__demo__"
    query = """
    INSERT INTO document (
        id, owner_key, sha256, filename, title, mime, byte_size, storage_path, status
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
    RETURNING id, title, filename, mime, byte_size, status, status_detail, error_code,
              page_count, chunk_count, created_at, ready_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query, document_id, owner_key, sha256, filename, title, mime, byte_size, storage_path
        )
        return DocumentOut(
            id=row["id"],
            title=row["title"],
            filename=row["filename"],
            mime=row["mime"],
            byte_size=row["byte_size"],
            status=DocumentStatus(row["status"]),
            status_detail=row["status_detail"],
            error_code=row["error_code"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            is_demo=is_demo,
            progress=0.0,
            created_at=row["created_at"],
            ready_at=row["ready_at"],
        )


async def get_document_by_sha256(
    pool: asyncpg.Pool,
    owner_key: str,
    sha256: str,
) -> Optional[DocumentOut]:
    """Retrieve existing document by sha256 and owner_key (deduplication check BE-03-R4)."""
    query = """
    SELECT id, title, filename, mime, byte_size, status, status_detail, error_code,
           page_count, chunk_count, created_at, ready_at, owner_key
    FROM document
    WHERE owner_key = $1 AND sha256 = $2
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, owner_key, sha256)
        if not row:
            return None
        return DocumentOut(
            id=row["id"],
            title=row["title"],
            filename=row["filename"],
            mime=row["mime"],
            byte_size=row["byte_size"],
            status=DocumentStatus(row["status"]),
            status_detail=row["status_detail"],
            error_code=row["error_code"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            is_demo=(row["owner_key"] == "__demo__"),
            progress=1.0 if row["status"] == "ready" else None,
            created_at=row["created_at"],
            ready_at=row["ready_at"],
        )


async def get_document_by_id(
    pool: asyncpg.Pool,
    document_id: UUID,
    owner_key: Optional[str] = None,
) -> Optional[Tuple[DocumentOut, str, str]]:
    """Retrieve document by ID. Returns (DocumentOut, storage_path, owner_key) or None."""
    query = """
    SELECT id, title, filename, mime, byte_size, status, status_detail, error_code,
           page_count, chunk_count, created_at, ready_at, owner_key, storage_path
    FROM document
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, document_id)
        if not row:
            return None

        # Visibility rule: if caller specifies owner_key, enforce caller ownership OR demo document (BE-12-R8)
        row_owner = row["owner_key"]
        if owner_key is not None and row_owner != "__demo__" and row_owner != owner_key:
            return None

        doc_out = DocumentOut(
            id=row["id"],
            title=row["title"],
            filename=row["filename"],
            mime=row["mime"],
            byte_size=row["byte_size"],
            status=DocumentStatus(row["status"]),
            status_detail=row["status_detail"],
            error_code=row["error_code"],
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            is_demo=(row_owner == "__demo__"),
            progress=1.0 if row["status"] == "ready" else None,
            created_at=row["created_at"],
            ready_at=row["ready_at"],
        )
        return doc_out, row["storage_path"], row_owner


async def list_documents(
    pool: asyncpg.Pool,
    owner_key: Optional[str],
    scope: Scope = Scope.ALL,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[DocumentOut], int]:
    """List documents visible to caller with pagination."""
    conditions = []
    params = []

    if scope == Scope.DEMO:
        conditions.append("owner_key = '__demo__'")
    elif scope == Scope.MINE:
        if not owner_key:
            return [], 0
        params.append(owner_key)
        conditions.append(f"owner_key = ${len(params)}")
    else:  # ALL
        if owner_key:
            params.append(owner_key)
            conditions.append(f"(owner_key = '__demo__' OR owner_key = ${len(params)})")
        else:
            conditions.append("owner_key = '__demo__'")

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

    count_query = f"SELECT COUNT(*) FROM document{where_clause}"
    
    params.extend([limit, offset])
    items_query = f"""
    SELECT id, title, filename, mime, byte_size, status, status_detail, error_code,
           page_count, chunk_count, created_at, ready_at, owner_key
    FROM document{where_clause}
    ORDER BY created_at DESC
    LIMIT ${len(params)-1} OFFSET ${len(params)}
    """

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_query, *params[:-2])
        rows = await conn.fetch(items_query, *params)

        items = [
            DocumentOut(
                id=row["id"],
                title=row["title"],
                filename=row["filename"],
                mime=row["mime"],
                byte_size=row["byte_size"],
                status=DocumentStatus(row["status"]),
                status_detail=row["status_detail"],
                error_code=row["error_code"],
                page_count=row["page_count"],
                chunk_count=row["chunk_count"],
                is_demo=(row["owner_key"] == "__demo__"),
                progress=1.0 if row["status"] == "ready" else None,
                created_at=row["created_at"],
                ready_at=row["ready_at"],
            )
            for row in rows
        ]
        return items, total


async def update_document_status(
    pool: asyncpg.Pool,
    document_id: UUID,
    status: DocumentStatus,
    status_detail: Optional[str] = None,
    error_code: Optional[str] = None,
) -> None:
    """Update document lifecycle status."""
    query = """
    UPDATE document
    SET status = $2::document_status,
        status_detail = $3,
        error_code = $4,
        ready_at = CASE WHEN $2::document_status = 'ready'::document_status THEN now() ELSE ready_at END
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(query, document_id, status.value, status_detail, error_code)


async def update_document_extraction(
    pool: asyncpg.Pool,
    document_id: UUID,
    page_count: Optional[int],
    char_count: int,
    chunk_count: int,
    title: str,
) -> None:
    """Record extraction and chunking metadata on document."""
    query = """
    UPDATE document
    SET page_count = $2,
        char_count = $3,
        chunk_count = $4,
        title = $5
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(query, document_id, page_count, char_count, chunk_count, title)


async def delete_document(
    pool: asyncpg.Pool,
    document_id: UUID,
    owner_key: str,
) -> bool:
    """Delete a document if owned by caller and not a demo document."""
    query = """
    DELETE FROM document
    WHERE id = $1 AND owner_key = $2 AND owner_key <> '__demo__'
    RETURNING storage_path
    """
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(query, document_id, owner_key)
        return deleted is not None
