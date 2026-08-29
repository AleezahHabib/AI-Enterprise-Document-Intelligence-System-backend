"""Unit tests for BE-11 Confidence Gate and Fallback.
Named by requirement IDs per BE-16-R4.
"""

from uuid import uuid4
import pytest
from app.core.config import Settings
from app.models.queries import (
    RefusalReason,
    RetrievalResult,
    RetrievedChunk,
)
from app.retrieval.gate import REFUSAL_MESSAGE, build_refusal_payload, evaluate_gate


def get_test_settings():
    return Settings(
        DATABASE_URL="postgresql://postgres:test@localhost:5432/test",
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_SERVICE_KEY="test_key",
        GEMINI_API_KEY="test_key",
        MIN_TOP_SIMILARITY=0.55,
        MIN_SUPPORTING_CHUNKS=2,
        MIN_SUPPORTING_SIMILARITY=0.45,
    )


def make_test_chunk(chunk_id: int, sim: float, doc_id=None, doc_title="Test Doc"):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=doc_id or uuid4(),
        document_title=doc_title,
        document_filename="test.pdf",
        content=f"Content for chunk {chunk_id}",
        page_from=1,
        page_to=1,
        section_path=None,
        char_start=0,
        char_end=20,
        similarity=sim,
        vector_rank=1,
        keyword_rank=1,
        rrf_score=0.03,
        used_in_context=True,
    )


def test_be_11_r4_gate_passes_when_both_thresholds_satisfied():
    """BE-11-R4: Gate passes when top similarity >= 0.55 and >=2 chunks >= 0.45."""
    settings = get_test_settings()
    chunks = [
        make_test_chunk(1, 0.72),
        make_test_chunk(2, 0.58),
        make_test_chunk(3, 0.35),
    ]
    retrieval_res = RetrievalResult(chunks=chunks, candidate_count=3, vector_hits=3, keyword_hits=0)
    passed, reason = evaluate_gate(retrieval_res, settings)
    assert passed is True
    assert reason is None


def test_be_11_r5_empty_retrieval_refuses_no_candidates():
    """BE-11-R5: Empty retrieval results refuse immediately with no_candidates."""
    settings = get_test_settings()
    retrieval_res = RetrievalResult(chunks=[], candidate_count=0, vector_hits=0, keyword_hits=0)
    passed, reason = evaluate_gate(retrieval_res, settings)
    assert passed is False
    assert reason == RefusalReason.NO_CANDIDATES


def test_be_11_r6_below_top_similarity_refuses():
    """BE-11-R6: Top similarity below 0.55 refuses with below_top_similarity."""
    settings = get_test_settings()
    chunks = [
        make_test_chunk(1, 0.52),  # < 0.55
        make_test_chunk(2, 0.48),
        make_test_chunk(3, 0.46),
    ]
    retrieval_res = RetrievalResult(chunks=chunks, candidate_count=3, vector_hits=3, keyword_hits=0)
    passed, reason = evaluate_gate(retrieval_res, settings)
    assert passed is False
    assert reason == RefusalReason.BELOW_TOP_SIMILARITY


def test_be_11_r7_insufficient_supporting_chunks_refuses():
    """BE-11-R7: Only 1 chunk >= 0.45 refuses with insufficient_supporting_chunks."""
    settings = get_test_settings()
    chunks = [
        make_test_chunk(1, 0.85),  # High top similarity
        make_test_chunk(2, 0.38),  # < 0.45 floor
        make_test_chunk(3, 0.25),
    ]
    retrieval_res = RetrievalResult(chunks=chunks, candidate_count=3, vector_hits=3, keyword_hits=0)
    passed, reason = evaluate_gate(retrieval_res, settings)
    assert passed is False
    assert reason == RefusalReason.INSUFFICIENT_SUPPORTING_CHUNKS


def test_be_11_r9_refusal_message_is_exact_verbatim_constant():
    """BE-11-R9: Refusal message matches verbatim specification string."""
    expected = (
        "I couldn't find enough information in the indexed documents to answer this question confidently. "
        "Answering without supporting evidence risks giving you something inaccurate."
    )
    assert REFUSAL_MESSAGE == expected


def test_be_11_r11_nearest_documents_capped_at_three():
    """BE-11-R11: Nearest documents payload returns up to 3 distinct documents."""
    doc_a, doc_b, doc_c, doc_d = uuid4(), uuid4(), uuid4(), uuid4()
    chunks = [
        make_test_chunk(1, 0.40, doc_id=doc_a, doc_title="Doc A"),
        make_test_chunk(2, 0.38, doc_id=doc_b, doc_title="Doc B"),
        make_test_chunk(3, 0.35, doc_id=doc_c, doc_title="Doc C"),
        make_test_chunk(4, 0.30, doc_id=doc_d, doc_title="Doc D"),
    ]
    retrieval_res = RetrievalResult(chunks=chunks, candidate_count=4, vector_hits=4, keyword_hits=0)
    payload = build_refusal_payload(RefusalReason.BELOW_TOP_SIMILARITY, retrieval_res)
    assert len(payload.nearest_documents) == 3
    assert payload.nearest_documents[0].document_title == "Doc A"
    assert payload.nearest_documents[0].top_similarity == 0.40
