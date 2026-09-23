from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.api.services import embeddings as embeddings_module
from app.core.config import settings


@pytest.fixture(autouse=True)
def clear_model_cache():
    embeddings_module.get_model.cache_clear()
    yield
    embeddings_module.get_model.cache_clear()


@patch.object(embeddings_module, "SentenceTransformer")
def test_dimension_mismatch_raises(mock_st_cls):
    mock_model = MagicMock()
    mock_model.get_embedding_dimension.return_value = settings.EMBEDDING_DIMENSION + 1
    mock_st_cls.return_value = mock_model

    with pytest.raises(embeddings_module.EmbeddingDimensionMismatch):
        embeddings_module.get_model()


@patch.object(embeddings_module, "SentenceTransformer")
def test_warm_up_loads_model(mock_st_cls):
    mock_model = MagicMock()
    mock_model.get_embedding_dimension.return_value = settings.EMBEDDING_DIMENSION
    mock_st_cls.return_value = mock_model

    embeddings_module.warm_up()

    mock_st_cls.assert_called_once_with(settings.EMBEDDING_MODEL)


@patch.object(embeddings_module, "get_model")
def test_embed_texts_uses_batch_size_and_returns_lists(mock_get_model):
    mock_model = MagicMock()
    mock_get_model.return_value = mock_model
    mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    vectors = embeddings_module.embed_texts([" passage one ", "passage two"])

    mock_model.encode.assert_called_once()
    args, kwargs = mock_model.encode.call_args
    assert args[0] == ["passage one", "passage two"]
    assert kwargs["batch_size"] == settings.EMBEDDING_BATCH_SIZE
    assert kwargs["normalize_embeddings"] is True
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@patch.object(embeddings_module, "get_model")
def test_embed_query_applies_prefix(mock_get_model):
    mock_model = MagicMock()
    mock_get_model.return_value = mock_model
    mock_model.encode.return_value = np.array([[1.0, 2.0]])

    vector = embeddings_module.embed_query("remote work policy")

    mock_model.encode.assert_called_once()
    texts = mock_model.encode.call_args[0][0]
    assert texts == [f"{settings.EMBEDDING_QUERY_PREFIX}remote work policy"]
    assert vector == [1.0, 2.0]


def test_embed_texts_empty_and_whitespace_only():
    assert embeddings_module.embed_texts([]) == []
    assert embeddings_module.embed_texts(["", "   "]) == []


def test_embed_query_rejects_empty():
    with pytest.raises(ValueError, match="empty query"):
        embeddings_module.embed_query("   ")


@pytest.mark.slow
def test_semantic_similarity_real_model():
    passage = embeddings_module.embed_texts(["Annual leave entitlement is 25 days per year."])[0]
    related = embeddings_module.embed_query("how many holiday days do I get")
    unrelated = embeddings_module.embed_query("what is the fire evacuation procedure")

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    assert dot(passage, related) > dot(passage, unrelated)
