"""Confidence Gate and deterministic refusal evaluation.
Governing spec: BE-11.
"""

from typing import Dict, List, Optional, Tuple
from uuid import UUID
from app.core.config import Settings
from app.models.queries import (
    NearestDocumentOut,
    RefusalPayloadOut,
    RefusalReason,
    RetrievalResult,
)

# BE-11-R9, BE-11-R10: Verbatim module constant for honest refusal
REFUSAL_MESSAGE = (
    "I couldn't find enough information in the indexed documents to answer this question confidently. "
    "Answering without supporting evidence risks giving you something inaccurate."
)


def evaluate_gate(
    retrieval_res: RetrievalResult,
    settings: Settings,
) -> Tuple[bool, Optional[RefusalReason]]:
    """Evaluate pre-generation confidence gate (BE-11 §5).
    
    Returns (True, None) if gate passes, or (False, RefusalReason) if refused.
    """
    if not retrieval_res.chunks:
        return False, RefusalReason.NO_CANDIDATES

    # Cosine similarity is in [0, 1] (BE-11-R6)
    top_similarity = max(c.similarity for c in retrieval_res.chunks)

    # Condition 1: top_similarity >= MIN_TOP_SIMILARITY (BE-11-R4)
    if top_similarity < settings.MIN_TOP_SIMILARITY:
        return False, RefusalReason.BELOW_TOP_SIMILARITY

    # Condition 2: count(similarity >= MIN_SUPPORTING_SIMILARITY) >= MIN_SUPPORTING_CHUNKS
    supporting_chunks = [
        c for c in retrieval_res.chunks
        if c.similarity >= settings.MIN_SUPPORTING_SIMILARITY
    ]
    if len(supporting_chunks) < settings.MIN_SUPPORTING_CHUNKS:
        return False, RefusalReason.INSUFFICIENT_SUPPORTING_CHUNKS

    return True, None


def build_refusal_payload(
    reason: RefusalReason,
    retrieval_res: RetrievalResult,
) -> RefusalPayloadOut:
    """Construct deterministic refusal payload with nearest documents (BE-11 §6)."""
    # Track best similarity per document ID (up to 3 documents, BE-11-R11)
    best_doc_sim: Dict[UUID, Tuple[str, float]] = {}

    for c in retrieval_res.chunks:
        doc_id = c.document_id
        if doc_id not in best_doc_sim or c.similarity > best_doc_sim[doc_id][1]:
            best_doc_sim[doc_id] = (c.document_title, c.similarity)

    # Sort by similarity descending and pick top 3
    sorted_docs = sorted(best_doc_sim.items(), key=lambda x: x[1][1], reverse=True)[:3]

    nearest_docs = [
        NearestDocumentOut(
            document_id=doc_id,
            document_title=title,
            top_similarity=round(sim, 4),
        )
        for doc_id, (title, sim) in sorted_docs
    ]

    return RefusalPayloadOut(
        reason=reason,
        message=REFUSAL_MESSAGE,
        nearest_documents=nearest_docs,
    )
