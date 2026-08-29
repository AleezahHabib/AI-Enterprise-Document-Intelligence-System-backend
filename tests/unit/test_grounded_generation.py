"""Unit tests for BE-09 RAG Generation and BE-10 Grounding & Citation Validation.
Named by requirement IDs per BE-16-R4.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from httpx import AsyncClient, ASGITransport

from app.core.text import normalize_for_match
from app.generation.validate import assemble_answer, validate_and_enrich
from app.main import app
from app.db.pool import get_pool
from app.models.queries import (
    EnrichedClaimOut,
    EnrichedCitationOut,
    RawCitationOut,
    RawClaimOut,
    RawGenerationOut,
    RetrievedChunk,
)


def make_context_chunk(chunk_id: int, content: str, title="Test Doc"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=uuid4(),
        document_title=title,
        document_filename="doc.pdf",
        content=content,
        page_from=5,
        page_to=5,
        section_path="Section 3 > Retention",
        char_start=100,
        char_end=100 + len(content),
        similarity=0.88,
        vector_rank=1,
        keyword_rank=1,
        rrf_score=0.03,
        used_in_context=True,
    )


def test_be_10_r2_unknown_chunk_id_rejected():
    """BE-10-R2: Citations with chunk_id not in context are rejected with UNKNOWN_CHUNK_ID."""
    context = [make_context_chunk(101, "Customer records are kept for 7 years.")]
    candidate = RawGenerationOut(
        status="answered",
        claims=[
            RawClaimOut(
                text="Records are kept for 7 years.",
                citations=[RawCitationOut(chunk_id=999, quote="Customer records are kept for 7 years.")],  # Unknown ID 999
            )
        ],
    )
    is_valid, claims, failures = validate_and_enrich(candidate, context)
    assert is_valid is False
    assert len(failures) == 1
    assert failures[0].reason == "UNKNOWN_CHUNK_ID"
    assert failures[0].chunk_id == 999


def test_be_10_r4_paraphrased_quote_rejected():
    """BE-10-R4: Paraphrased quotes failing substring match are rejected with QUOTE_NOT_FOUND."""
    context = [make_context_chunk(101, "Customer records shall be retained for seven (7) years.")]
    candidate = RawGenerationOut(
        status="answered",
        claims=[
            RawClaimOut(
                text="Records are stored for seven years.",
                citations=[RawCitationOut(chunk_id=101, quote="Customer records are saved for 7 years.")],  # Paraphrased
            )
        ],
    )
    is_valid, claims, failures = validate_and_enrich(candidate, context)
    assert is_valid is False
    assert len(failures) == 1
    assert failures[0].reason == "QUOTE_NOT_FOUND"


def test_be_10_r8_normalization_handles_curly_quotes_and_whitespace():
    """BE-10-R8: Matching succeeds across curly quotes, dashes, and extra whitespace."""
    doc_text = 'The vendor’s SLA states: “Monthly availability is 99.95%—measured 24/7.”'
    model_quote = 'the vendor\'s sla states: "monthly availability is 99.95%-measured 24/7."'
    
    assert normalize_for_match(model_quote) in normalize_for_match(doc_text)


def test_be_10_r12_enriched_citation_carries_database_metadata():
    """BE-10-R12: Validated citations are enriched with parent document metadata and page."""
    context = [make_context_chunk(101, "Customer records must be retained for seven years.", title="Policy 2026")]
    candidate = RawGenerationOut(
        status="answered",
        claims=[
            RawClaimOut(
                text="Customer records are retained for 7 years.",
                citations=[RawCitationOut(chunk_id=101, quote="Customer records must be retained for seven years.")],
            )
        ],
    )
    is_valid, enriched_claims, failures = validate_and_enrich(candidate, context)
    assert is_valid is True
    assert len(enriched_claims) == 1
    
    cit = enriched_claims[0].citations[0]
    assert cit.chunk_id == 101
    assert cit.document_title == "Policy 2026"
    assert cit.page == 5
    assert cit.section_path == "Section 3 > Retention"
    assert cit.char_start is not None


def test_be_09_r22_answer_assembled_by_space_joining_claims():
    """BE-09-R22: Final answer prose is assembled by joining claim texts with spaces."""
    claims = [
        EnrichedClaimOut(text="First factual claim.", citations=[]),
        EnrichedClaimOut(text="Second factual claim.", citations=[]),
    ]
    answer = assemble_answer(claims)
    assert answer == "First factual claim. Second factual claim."


def test_claim_not_supported_when_quote_is_unrelated():
    """Verify that a claim with a verbatim quote from an unrelated topic/document fails support validation."""
    context = [make_context_chunk(101, "Vendor guarantees a monthly uptime service level of 99.95% across all production API gateways.", title="MSA Agreement")]
    candidate = RawGenerationOut(
        status="answered",
        claims=[
            RawClaimOut(
                text="Open Book Contract Management guidance is intended for central government departments.",
                citations=[RawCitationOut(chunk_id=101, quote="Vendor guarantees a monthly uptime service level of 99.95% across all production API gateways.")],
            )
        ],
    )
    is_valid, claims, failures = validate_and_enrich(candidate, context)
    assert is_valid is False
    assert len(failures) == 1
    assert failures[0].reason == "CLAIM_NOT_SUPPORTED"


def test_claim_supported_when_quote_actually_proves_claim():
    """Verify that a claim supported by its cited passage passes validation."""
    doc_content = "This Guidance is for the use of central government departments planning the management of contracts for IT, Business Process Outsourcing (BPO) and Facilities Management (FM)."
    context = [make_context_chunk(101, doc_content, title="OBCM Guidance")]
    candidate = RawGenerationOut(
        status="answered",
        claims=[
            RawClaimOut(
                text="The guidance is designed for central government departments planning the management of IT and outsourcing contracts.",
                citations=[RawCitationOut(chunk_id=101, quote=doc_content)],
            )
        ],
    )
    is_valid, enriched_claims, failures = validate_and_enrich(candidate, context)
    assert is_valid is True
    assert len(failures) == 0
    assert len(enriched_claims) == 1




