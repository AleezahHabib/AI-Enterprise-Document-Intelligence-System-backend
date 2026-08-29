"""Document API request and response models matching BE-12 OpenAPI spec.
Governing spec: BE-12 §6.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class Scope(str, Enum):
    DEMO = "demo"
    MINE = "mine"
    ALL = "all"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class DocumentOut(BaseModel):
    id: UUID
    title: str
    filename: str
    mime: str
    byte_size: int
    status: DocumentStatus
    status_detail: Optional[str] = None
    error_code: Optional[str] = None
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    is_demo: bool
    progress: Optional[float] = None
    created_at: datetime
    ready_at: Optional[datetime] = None


class DocumentListOut(BaseModel):
    items: List[DocumentOut]
    total: int


class ChunkWithDocument(BaseModel):
    id: int
    document_id: UUID
    document_title: str
    ordinal: int
    page_from: Optional[int]
    page_to: Optional[int]
    section_path: Optional[str]
    char_start: int
    char_end: int
    content: str
    token_count: int
    embedding_model: Optional[str] = None
