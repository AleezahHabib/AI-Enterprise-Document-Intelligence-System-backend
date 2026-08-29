"""Generation and repair orchestration with Gemini 2.0 Flash structured outputs.
Governing spec: BE-09, ADR-0001.
"""

import json
from typing import List, Optional, Tuple
from google import genai
from google.genai import types

from app.core.config import Settings
from app.core.errors import UpstreamRateLimitedError, ServiceUnavailableError, GenerationFailedError
from app.core.logging import logger
from app.generation.prompt import SYSTEM_INSTRUCTION, build_user_prompt, build_repair_prompt
from app.generation.validate import validate_and_enrich, assemble_answer
from app.models.queries import (
    EnrichedClaimOut,
    QueryOutcome,
    RawGenerationOut,
    RefusalReason,
    RetrievedChunk,
    ValidationFailure,
)


async def execute_generation_pipeline(
    question: str,
    context_chunks: List[RetrievedChunk],
    settings: Settings,
) -> Tuple[QueryOutcome, Optional[str], Optional[List[EnrichedClaimOut]], Optional[RefusalReason], int, List[dict]]:
    """Execute generation, validation, and repair loop.
    
    Returns:
      (outcome, answer_text, enriched_claims, refusal_reason, validation_attempts, validation_errors_log)
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    user_prompt = build_user_prompt(question, context_chunks)

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=settings.GENERATION_TEMPERATURE,
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=RawGenerationOut,
    )

    validation_errors_log: List[dict] = []
    validation_attempts = 1

    try:
        # Attempt 1: Initial generation
        response = client.models.generate_content(
            model=settings.GENERATION_MODEL,
            contents=[user_prompt],
            config=config,
        )
        candidate: RawGenerationOut = response.parsed

    except Exception as e:
        err_msg = str(e).lower()
        logger.error(f"Gemini generation call failed: {e}")
        if "429" in err_msg or "quota" in err_msg or "rate limit" in err_msg:
            raise UpstreamRateLimitedError(retry_after=30)
        elif "503" in err_msg or "unavailable" in err_msg:
            raise ServiceUnavailableError()
        else:
            raise GenerationFailedError()

    if candidate is None or candidate.status == "insufficient_context":
        return (
            QueryOutcome.INSUFFICIENT_CONTEXT,
            None,
            None,
            RefusalReason.MODEL_DECLINED,
            validation_attempts,
            validation_errors_log,
        )

    # Validate Attempt 1
    is_valid, enriched_claims, failures = validate_and_enrich(candidate, context_chunks)
    if is_valid and enriched_claims:
        answer_prose = assemble_answer(enriched_claims)
        return (
            QueryOutcome.ANSWERED,
            answer_prose,
            enriched_claims,
            None,
            validation_attempts,
            validation_errors_log,
        )

    # Record Attempt 1 failures
    for f in failures:
        validation_errors_log.append({
            "attempt": 1,
            "claim": f.claim_text,
            "chunk_id": f.chunk_id,
            "quote": f.quote,
            "reason": f.reason,
        })

    # BE-09-R18: Exactly one repair attempt
    validation_attempts = 2
    repair_prompt = build_repair_prompt(failures)

    try:
        # Send history + repair prompt
        repair_contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]),
            types.Content(role="model", parts=[types.Part.from_text(text=json.dumps(candidate.model_dump()))]),
            types.Content(role="user", parts=[types.Part.from_text(text=repair_prompt)]),
        ]

        repair_response = client.models.generate_content(
            model=settings.GENERATION_MODEL,
            contents=repair_contents,
            config=config,
        )
        repair_candidate: RawGenerationOut = repair_response.parsed

    except Exception as e:
        logger.warning(f"Gemini repair generation call failed: {e}")
        return (
            QueryOutcome.INSUFFICIENT_CONTEXT,
            None,
            None,
            RefusalReason.VALIDATION_FAILED,
            validation_attempts,
            validation_errors_log,
        )

    if repair_candidate is None or repair_candidate.status == "insufficient_context":
        return (
            QueryOutcome.INSUFFICIENT_CONTEXT,
            None,
            None,
            RefusalReason.MODEL_DECLINED,
            validation_attempts,
            validation_errors_log,
        )

    # Validate Attempt 2
    is_valid_2, enriched_claims_2, failures_2 = validate_and_enrich(repair_candidate, context_chunks)
    if is_valid_2 and enriched_claims_2:
        answer_prose = assemble_answer(enriched_claims_2)
        return (
            QueryOutcome.ANSWERED,
            answer_prose,
            enriched_claims_2,
            None,
            validation_attempts,
            validation_errors_log,
        )

    for f in failures_2:
        validation_errors_log.append({
            "attempt": 2,
            "claim": f.claim_text,
            "chunk_id": f.chunk_id,
            "quote": f.quote,
            "reason": f.reason,
        })

    # BE-09-R20: Repair also failed -> return insufficient_context with validation_failed
    return (
        QueryOutcome.INSUFFICIENT_CONTEXT,
        None,
        None,
        RefusalReason.VALIDATION_FAILED,
        validation_attempts,
        validation_errors_log,
    )
