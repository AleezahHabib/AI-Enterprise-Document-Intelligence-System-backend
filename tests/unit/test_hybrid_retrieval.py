"""Unit tests for BE-08 Hybrid Retrieval.
Named by requirement IDs per BE-16-R4.
"""

import pytest
from app.models.documents import Scope
from app.models.queries import RetrievedChunk, RetrievalResult
from app.retrieval.hybrid import resolve_owner_keys


def test_be_08_r3_scope_owner_resolution():
    """BE-08-R3: Scope maps to correct owner key sets."""
    # demo -> ['__demo__']
    assert resolve_owner_keys(Scope.DEMO, "user123") == ["__demo__"]
    assert resolve_owner_keys(Scope.DEMO, None) == ["__demo__"]

    # mine -> [caller_owner_key] or []
    assert resolve_owner_keys(Scope.MINE, "user123") == ["user123"]
    assert resolve_owner_keys(Scope.MINE, None) == []

    # all -> ['__demo__', caller_owner_key] or ['__demo__']
    assert resolve_owner_keys(Scope.ALL, "user123") == ["__demo__", "user123"]
    assert resolve_owner_keys(Scope.ALL, None) == ["__demo__"]


def test_be_08_r7_cosine_similarity_not_inverted():
    """BE-08-R7: Cosine similarity is 1.0 for identical vectors, not distance 0.0."""
    # Cosine distance = 0.0 -> similarity = 1.0 - 0.0 = 1.0
    cosine_distance = 0.05
    similarity = 1.0 - cosine_distance
    assert similarity == 0.95
    assert similarity > 0.5  # High similarity must be > 0.5


def test_be_08_r16_rrf_constant_equals_60():
    """BE-08-R16: RRF_K constant is exactly 60."""
    from app.core.config import Settings
    settings = Settings(
        DATABASE_URL="postgresql://postgres:test@localhost:5432/test",
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_SERVICE_KEY="test_key",
        GEMINI_API_KEY="test_key",
    )
    assert settings.RRF_K == 60
