"""Query, Retrieval, Claim, and Citation models matching BE-12 OpenAPI spec.
Governing specs: BE-08 §10, BE-09 §6, BE-10 §6, BE-11 §6, BE-12 §6.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from uuid import UUID
from pydantic import BaseModel, Field
from app.models.documents import Scope


class QueryOutcome(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class RefusalReason(str, Enum):
    NO_CANDIDATES = "no_candidates"
    BELOW_TOP_SIMILARITY = "below_top_similarity"
    INSUFFICIENT_SUPPORTING_CHUNKS = "insufficient_supporting_chunks"
    MODEL_DECLINED = "model_declined"
    VALIDATION_FAILED = "validation_failed"


# ---------------------------------------------------------------------------
# Internal Dataclasses for Retrieval & Validation Pipeline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: UUID
    document_title: str
    document_filename: str
    content: str
    page_from: Optional[int]
    page_to: Optional[int]
    section_path: Optional[str]
    char_start: int
    char_end: int
    similarity: float                 # Cosine similarity (1 - distance)
    vector_rank: Optional[int]
    keyword_rank: Optional[int]
    rrf_score: float
    used_in_context: bool = False


@dataclass(frozen=True)
class RetrievalResult:
    chunks: List[RetrievedChunk]       # Ordered by rrf_score desc
    candidate_count: int
    vector_hits: int
    keyword_hits: int


@dataclass(frozen=True)
class ValidationFailure:
    claim_text: str
    chunk_id: int
    quote: str
    reason: str                        # "UNKNOWN_CHUNK_ID" | "QUOTE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Generation Structured Output Schemas (BE-09 §6)
# ---------------------------------------------------------------------------

class RawCitationOut(BaseModel):
    chunk_id: int = Field(..., description="chunk_id from the excerpt header")
    quote: str = Field(..., min_length=10, max_length=500, description="verbatim text from that excerpt")


class RawClaimOut(BaseModel):
    text: str = Field(..., min_length=3, max_length=1000)
    citations: List[RawCitationOut] = Field(..., min_length=1)


class RawGenerationOut(BaseModel):
    status: Literal["answered", "insufficient_context"]
    claims: List[RawClaimOut] = Field(default_factory=list)
    reason: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Public API Request and Response Models (BE-12 §6)
# ---------------------------------------------------------------------------

class QueryIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    scope: Scope = Scope.ALL
    document_ids: Optional[List[UUID]] = None
    include_retrieval: bool = False


class EnrichedCitationOut(BaseModel):
    chunk_id: int
    document_id: UUID
    document_title: str
    page: Optional[Union[int, str]] = None
    section_path: Optional[str] = None
    quote: str
    char_start: Optional[int] = None
    char_end: Optional[int] = None


class EnrichedClaimOut(BaseModel):
    text: str
    citations: List[EnrichedCitationOut]


class NearestDocumentOut(BaseModel):
    document_id: UUID
    document_title: str
    top_similarity: float


class RetrievalChunkOut(BaseModel):
    chunk_id: int
    document_id: UUID
    document_title: str
    similarity: float
    vector_rank: Optional[int]
    keyword_rank: Optional[int]
    rrf_score: float
    used_in_context: bool
    section_path: Optional[str]
    page_from: Optional[int]
    page_to: Optional[int]
    char_start: int
    char_end: int
    content: str


class RetrievalInspectorOut(BaseModel):
    chunks: List[RetrievalChunkOut]
    candidate_count: int
    vector_hits: int
    keyword_hits: int


class RefusalPayloadOut(BaseModel):
    reason: RefusalReason
    message: str
    nearest_documents: List[NearestDocumentOut]


class QueryResponseOut(BaseModel):
    id: UUID
    question: str
    status: QueryOutcome
    answer: Optional[str] = None
    claims: Optional[List[EnrichedClaimOut]] = None
    refusal: Optional[RefusalPayloadOut] = None
    latency_ms: int
    retrieval: Optional[RetrievalInspectorOut] = None
    created_at: datetime
