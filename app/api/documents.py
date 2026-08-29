"""Documents API router.
Governing spec: BE-03, BE-12 §4, BE-14.
"""

import hashlib
import io
import uuid
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Header,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
import asyncpg

from app.core.config import Settings, get_settings
from app.core.errors import (
    DemoDocumentImmutableError,
    EmptyFileError,
    IdentityRequiredError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.api.deps import Identity, get_identity
from app.db.pool import get_pool
from app.db.documents import (
    create_document,
    delete_document as db_delete_document,
    get_document_by_id,
    get_document_by_sha256,
    list_documents as db_list_documents,
)
from app.models.documents import DocumentListOut, DocumentOut, Scope
from app.storage.supabase import put_object, get_object, delete_object
from app.ingestion.pipeline import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

PDF_MAGIC = b"%PDF-"
DOCX_MAGIC = b"PK\x03\x04"


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    response: Response,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings),
) -> DocumentOut:
    """Upload a PDF or DOCX file for asynchronous ingestion."""
    # BE-12-R8: Upload requires an owner key (session or user)
    if not identity.owner_key:
        raise IdentityRequiredError()

    # Read and validate file size without unbounded buffering
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)
    if len(file_bytes) > max_bytes:
        raise PayloadTooLargeError()

    if len(file_bytes) == 0:
        raise EmptyFileError()

    # BE-03-R2: Validate MIME by magic bytes, not file extension
    mime: str
    if file_bytes.startswith(PDF_MAGIC):
        mime = "application/pdf"
    elif file_bytes.startswith(DOCX_MAGIC):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise UnsupportedMediaTypeError()

    filename = file.filename or "untitled"
    doc_title = title.strip() if title and title.strip() else filename.rsplit(".", 1)[0]
    sha256 = hashlib.sha256(file_bytes).hexdigest()

    # BE-03-R4: Deduplication check
    existing_doc = await get_document_by_sha256(pool, identity.owner_key, sha256)
    if existing_doc:
        if existing_doc.status == DocumentStatus.FAILED:
            await update_document_status(pool, existing_doc.id, DocumentStatus.PENDING)
            background_tasks.add_task(ingest_document, existing_doc.id, pool, settings)
            existing_doc.status = DocumentStatus.PENDING
            existing_doc.status_detail = None
            existing_doc.error_code = None
        response.status_code = status.HTTP_200_OK
        return existing_doc

    doc_id = uuid.uuid4()
    storage_path = f"{identity.owner_key}/{doc_id}/{filename}"

    # Write to storage
    await put_object(storage_path, file_bytes, mime, settings)

    # Insert document row in 'pending' status
    doc_out = await create_document(
        pool=pool,
        document_id=doc_id,
        owner_key=identity.owner_key,
        sha256=sha256,
        filename=filename,
        title=doc_title,
        mime=mime,
        byte_size=len(file_bytes),
        storage_path=storage_path,
    )

    # Queue ingestion pipeline in background (BE-03-R6)
    background_tasks.add_task(ingest_document, doc_id, pool, settings)

    return doc_out


@router.get("", response_model=DocumentListOut)
async def list_documents(
    scope: Scope = Scope.ALL,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
) -> DocumentListOut:
    """List documents visible to the caller."""
    items, total = await db_list_documents(
        pool=pool,
        owner_key=identity.owner_key,
        scope=scope,
        limit=limit,
        offset=offset,
    )
    return DocumentListOut(items=items, total=total)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
) -> DocumentOut:
    """Get document details and processing status."""
    doc_tuple = await get_document_by_id(pool, document_id, identity.owner_key)
    if not doc_tuple:
        raise NotFoundError()
    return doc_tuple[0]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete a document and all its chunks."""
    doc_tuple = await get_document_by_id(pool, document_id, identity.owner_key)
    if not doc_tuple:
        raise NotFoundError()

    doc_out, storage_path, _ = doc_tuple
    if doc_out.is_demo:
        raise DemoDocumentImmutableError()

    deleted = await db_delete_document(pool, document_id, identity.owner_key)
    if not deleted:
        raise NotFoundError()

    # Delete storage object in background/async
    await delete_object(storage_path, settings)


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: UUID,
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings),
):
    """Retrieve original file stream for citation highlighting."""
    doc_tuple = await get_document_by_id(pool, document_id, identity.owner_key)
    if not doc_tuple:
        raise NotFoundError()

    doc_out, storage_path, _ = doc_tuple
    file_bytes = await get_object(storage_path, settings)

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=doc_out.mime,
        headers={"Content-Disposition": f'inline; filename="{doc_out.filename}"'},
    )
