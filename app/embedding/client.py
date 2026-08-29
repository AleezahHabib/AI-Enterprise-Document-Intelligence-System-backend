"""Gemini embedding client.
Governing spec: BE-06, ADR-0001, ADR-0002.
"""

import math
from typing import List
from google import genai
from google.genai import types

from app.core.config import Settings
from app.core.errors import UpstreamRateLimitedError, ServiceUnavailableError, EmbeddingFailedError
from app.core.logging import logger


def l2_normalize(vector: List[float]) -> List[float]:
    """L2-normalize a float vector (BE-06-R8)."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm < 1e-12:
        return vector
    return [x / norm for x in vector]


def format_halfvec_literal(vector: List[float]) -> str:
    """Format a float vector as a PostgreSQL bracketed vector literal string."""
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


class GeminiEmbeddingClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed document chunks using task_type="RETRIEVAL_DOCUMENT" (BE-06-R3)."""
        return await self._embed_batch(texts, task_type="RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> List[float]:
        """Embed search query using task_type="RETRIEVAL_QUERY" (BE-06-R4)."""
        results = await self._embed_batch([text], task_type="RETRIEVAL_QUERY")
        return results[0]

    async def _embed_batch(self, texts: List[str], task_type: str) -> List[List[float]]:
        """Call Gemini embed_content API with exponential backoff retries and apply L2 normalization."""
        if not texts:
            return []

        import asyncio
        import re

        max_retries = max(8, self.settings.GEMINI_MAX_RETRIES)
        last_exception = None

        for attempt in range(max_retries):
            try:
                config = types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self.settings.EMBEDDING_DIMENSIONS,
                )
                
                response = self.client.models.embed_content(
                    model=self.settings.EMBEDDING_MODEL,
                    contents=texts,
                    config=config,
                )

                results: List[List[float]] = []
                for emb in response.embeddings:
                    values = emb.values
                    norm_values = l2_normalize(values)
                    results.append(norm_values)

                return results

            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                logger.warning(f"Gemini embedding call attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if "429" in err_msg or "quota" in err_msg or "rate limit" in err_msg or "resource_exhausted" in err_msg:
                    # Dynamically extract upstream recommended retry delay if present e.g. "retry in 57.14s"
                    delay_match = re.search(r"retry (?:in |after )?(\d+(?:\.\d+)?)s?", err_msg)
                    if delay_match:
                        sleep_time = float(delay_match.group(1)) + 2.0
                    else:
                        sleep_time = min(65.0, (2.0 ** attempt) + 2.0)
                    
                    logger.info(f"Rate limited by Gemini API. Waiting {sleep_time:.1f}s before retry...")
                    await asyncio.sleep(sleep_time)
                elif "503" in err_msg or "unavailable" in err_msg:
                    await asyncio.sleep(2.0)
                else:
                    await asyncio.sleep(1.0)

        err_msg = str(last_exception).lower() if last_exception else ""
        if "429" in err_msg or "quota" in err_msg or "rate limit" in err_msg:
            raise UpstreamRateLimitedError(retry_after=30)
        elif "503" in err_msg or "unavailable" in err_msg:
            raise ServiceUnavailableError()
        else:
            raise EmbeddingFailedError()
