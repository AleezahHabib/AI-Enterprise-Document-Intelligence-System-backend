import re
from typing import Dict, List, Optional, Set, Tuple, Union
from app.core.text import normalize_for_match
from app.models.queries import (
    EnrichedCitationOut,
    EnrichedClaimOut,
    RawGenerationOut,
    RetrievedChunk,
    ValidationFailure,
)

STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once",
    "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd",
    "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}


def extract_content_tokens(text: str) -> Set[str]:
    """Extract substantive lowercased alphanumeric tokens excluding stopwords."""
    norm = normalize_for_match(text)
    tokens = re.findall(r"\b[a-z0-9]{2,}\b", norm)
    return {t for t in tokens if t not in STOPWORDS}


def does_quote_support_claim(claim_text: str, quote: str, chunk_content: str) -> bool:
    """Verify that the cited quote and chunk substantively support the claim."""
    claim_tokens = extract_content_tokens(claim_text)
    if not claim_tokens:
        return True

    quote_tokens = extract_content_tokens(quote)
    if not quote_tokens or len(quote_tokens) < 1:
        return False

    quote_overlap = claim_tokens.intersection(quote_tokens)
    if not quote_overlap:
        return False

    # At least 25% of claim's content tokens (or at least 1 token for short claims, 2 for longer claims)
    min_required = 1 if len(claim_tokens) <= 2 else max(2, int(len(claim_tokens) * 0.25))
    return len(quote_overlap) >= min_required


def compute_quote_offsets(
    quote: str,
    chunk_content: str,
    chunk_char_start: int,
) -> Tuple[Optional[int], Optional[int]]:
    """Find exact character offset of quote in chunk content (BE-10-R15, BE-10-R16)."""
    norm_quote = normalize_for_match(quote)
    norm_content = normalize_for_match(chunk_content)

    # First attempt exact raw match
    raw_idx = chunk_content.find(quote)
    if raw_idx != -1:
        return chunk_char_start + raw_idx, chunk_char_start + raw_idx + len(quote)

    # Normalized match check
    norm_idx = norm_content.find(norm_quote)
    if norm_idx != -1:
        # If lengths match exactly under normalized text
        if len(norm_quote) == len(quote):
            return chunk_char_start + norm_idx, chunk_char_start + norm_idx + len(quote)

    # BE-10-R16: If offsets shifted and cannot be determined with certainty, return None
    return None, None


def validate_and_enrich(
    candidate: RawGenerationOut,
    context_chunks: List[RetrievedChunk],
) -> Tuple[bool, Optional[List[EnrichedClaimOut]], List[ValidationFailure]]:
    """Validate candidate response against context chunks and enrich citations.
    
    Returns:
      (True, enriched_claims, []) on success
      (False, None, failures) on validation failure
    """
    if candidate.status != "answered":
        return True, None, []

    if not candidate.claims:
        # BE-09-R15: answered with 0 claims is insufficient_context
        return False, None, []

    chunk_map: Dict[int, RetrievedChunk] = {c.chunk_id: c for c in context_chunks}
    failures: List[ValidationFailure] = []
    enriched_claims: List[EnrichedClaimOut] = []

    for claim in candidate.claims:
        if not claim.citations:
            # BE-10-R6: Claim must have >= 1 citation
            failures.append(
                ValidationFailure(
                    claim_text=claim.text,
                    chunk_id=-1,
                    quote="",
                    reason="NO_CITATIONS",
                )
            )
            continue

        enriched_citations: List[EnrichedCitationOut] = []
        claim_has_error = False

        for cit in claim.citations:
            # Rule 1: Membership validation (BE-10-R2)
            if cit.chunk_id not in chunk_map:
                failures.append(
                    ValidationFailure(
                        claim_text=claim.text,
                        chunk_id=cit.chunk_id,
                        quote=cit.quote,
                        reason="UNKNOWN_CHUNK_ID",
                    )
                )
                claim_has_error = True
                continue

            chunk = chunk_map[cit.chunk_id]

            # Rule 2: Verbatim quote validation (BE-10-R4, BE-10-R10)
            norm_quote = normalize_for_match(cit.quote)
            norm_chunk = normalize_for_match(chunk.content)

            if norm_quote not in norm_chunk:
                failures.append(
                    ValidationFailure(
                        claim_text=claim.text,
                        chunk_id=cit.chunk_id,
                        quote=cit.quote,
                        reason="QUOTE_NOT_FOUND",
                    )
                )
                claim_has_error = True
                continue

            # Rule 3: Support verification (quote must actually support the claim)
            if not does_quote_support_claim(claim.text, cit.quote, chunk.content):
                failures.append(
                    ValidationFailure(
                        claim_text=claim.text,
                        chunk_id=cit.chunk_id,
                        quote=cit.quote,
                        reason="CLAIM_NOT_SUPPORTED",
                    )
                )
                claim_has_error = True
                continue

            # Enrichment (BE-10-R12–R16)
            quote_char_start, quote_char_end = compute_quote_offsets(
                cit.quote, chunk.content, chunk.char_start
            )

            page_val: Optional[Union[int, str]] = None
            if chunk.page_from is not None:
                if chunk.page_to is not None and chunk.page_from != chunk.page_to:
                    page_val = f"{chunk.page_from}–{chunk.page_to}"
                else:
                    page_val = chunk.page_from

            enriched_citations.append(
                EnrichedCitationOut(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    page=page_val,
                    section_path=chunk.section_path,
                    quote=cit.quote,
                    char_start=quote_char_start,
                    char_end=quote_char_end,
                )
            )

        if not claim_has_error and enriched_citations:
            enriched_claims.append(
                EnrichedClaimOut(
                    text=claim.text,
                    citations=enriched_citations,
                )
            )

    if failures or not enriched_claims:
        return False, None, failures

    return True, enriched_claims, []


def assemble_answer(claims: List[EnrichedClaimOut]) -> str:
    """Deterministically assemble answer prose by joining claim texts (BE-09-R22)."""
    return " ".join(c.text.strip() for c in claims if c.text.strip())

