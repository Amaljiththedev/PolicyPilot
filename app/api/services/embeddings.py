"""Turn text into vectors with a local sentence-transformers model.

No API calls, no rate limits, no cost. The model loads once per process
and stays resident, so the first call is slow and the rest are not.
"""
import logging
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingDimensionMismatch(RuntimeError):
    """Model output width doesn't match the database column."""


class EmbeddingError(RuntimeError):
    """The model failed to produce vectors."""


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    """Load the model once.

    First call downloads it (~130MB for bge-small) and takes several seconds.
    Cached for the life of the process, so never call this inside a loop.
    """
    logger.info("loading embedding model %s", settings.EMBEDDING_MODEL)
    model = SentenceTransformer(settings.EMBEDDING_MODEL)

    actual = model.get_sentence_embedding_dimension()
    if actual != settings.EMBEDDING_DIMENSION:
        raise EmbeddingDimensionMismatch(
            f"{settings.EMBEDDING_MODEL} produces {actual}-dimensional vectors, "
            f"but EMBEDDING_DIMENSION is {settings.EMBEDDING_DIMENSION} and "
            f"chunks.embedding was created at that width. "
            f"Set EMBEDDING_DIMENSION={actual} in .env, then "
            f"docker compose down -v && docker compose up -d && "
            f"python -m scripts.create_tables"
        )

    logger.info("embedding model ready, dimension %d", actual)
    return model


def warm_up() -> None:
    """Load the model at startup so the first request isn't slow.

    Call from a FastAPI lifespan handler. Also means a dimension mismatch
    fails the app at boot rather than mid-ingestion.
    """
    get_model()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed document chunks.

    Pass the whole list in one call — the batching is where the speed is.
    Calling this per chunk is roughly an order of magnitude slower.
    """
    if not texts:
        return []

    cleaned = [t.strip() for t in texts if t and t.strip()]
    if not cleaned:
        return []

    try:
        vectors = get_model().encode(
            cleaned,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
    except EmbeddingDimensionMismatch:
        raise
    except Exception as exc:
        raise EmbeddingError(f"embedding failed for {len(cleaned)} texts: {exc}") from exc

    # pgvector wants plain lists, not numpy arrays.
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a search query.

    BGE models are trained asymmetrically: queries carry an instruction
    prefix, passages don't. Using the same function for both loses a point
    or two of recall, in whichever direction you get it wrong.
    """
    if not text or not text.strip():
        raise ValueError("cannot embed an empty query")

    prefix = settings.EMBEDDING_QUERY_PREFIX
    prepared = f"{prefix}{text.strip()}" if prefix else text.strip()

    vectors = embed_texts([prepared])
    if not vectors:
        raise EmbeddingError("query produced no vector")
    return vectors[0]