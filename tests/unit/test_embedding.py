"""Unit tests for BE-06 Embedding Pipeline.
Named by requirement IDs per BE-16-R4.
"""

import math
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import Settings
from app.embedding.client import GeminiEmbeddingClient, l2_normalize


def get_test_settings():
    return Settings(
        DATABASE_URL="postgresql://postgres:test@localhost:5432/test",
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_SERVICE_KEY="test_key",
        GEMINI_API_KEY="test_key",
        EMBEDDING_MODEL="gemini-embedding-001",
        EMBEDDING_DIMENSIONS=768,
    )


def test_be_06_r8_embedding_dimensions_equals_768_l2_normalized():
    """BE-06-R8: Vectors are L2-normalized with norm = 1.0."""
    raw_vec = [1.0] * 768
    norm_vec = l2_normalize(raw_vec)
    assert len(norm_vec) == 768
    norm = math.sqrt(sum(x * x for x in norm_vec))
    assert abs(norm - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_be_06_r3_chunks_use_retrieval_document_task_type():
    """BE-06-R3: Chunk embedding calls Gemini with task_type='RETRIEVAL_DOCUMENT'."""
    settings = get_test_settings()
    client = GeminiEmbeddingClient(settings)

    mock_emb = MagicMock()
    mock_emb.values = [0.1] * 768
    mock_response = MagicMock()
    mock_response.embeddings = [mock_emb]

    with patch.object(client.client.models, "embed_content", return_value=mock_response) as mock_call:
        vectors = await client.embed_documents(["Sample chunk content"])
        assert len(vectors) == 1
        assert len(vectors[0]) == 768
        
        # Verify task_type in config argument
        call_kwargs = mock_call.call_args.kwargs
        config = call_kwargs.get("config")
        assert config.task_type == "RETRIEVAL_DOCUMENT"
        assert config.output_dimensionality == 768


@pytest.mark.asyncio
async def test_be_06_r4_queries_use_retrieval_query_task_type():
    """BE-06-R4: Search query embedding calls Gemini with task_type='RETRIEVAL_QUERY'."""
    settings = get_test_settings()
    client = GeminiEmbeddingClient(settings)

    mock_emb = MagicMock()
    mock_emb.values = [0.1] * 768
    mock_response = MagicMock()
    mock_response.embeddings = [mock_emb]

    with patch.object(client.client.models, "embed_content", return_value=mock_response) as mock_call:
        vector = await client.embed_query("How long are records kept?")
        assert len(vector) == 768
        
        call_kwargs = mock_call.call_args.kwargs
        config = call_kwargs.get("config")
        assert config.task_type == "RETRIEVAL_QUERY"
        assert config.output_dimensionality == 768
