from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings

settings = get_settings()

SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""]


def chunk_recursive(text: str, chunk_size: int, overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        separators=SEPARATORS,
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )
    return splitter.split_text(text)


def chunk_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Blind character windows. The ablation baseline."""
    step = chunk_size - overlap
    chunks = []
    for i in range(0, len(text), step):
        piece = text[i:i + chunk_size]
        # A trailing window no longer than the overlap is already fully
        # contained in the previous chunk — storing it would put a duplicate
        # vector in the database.
        if i > 0 and len(piece) <= overlap:
            break
        chunks.append(piece)
    return chunks


STRATEGIES = {"recursive": chunk_recursive, "fixed": chunk_fixed}


def chunk_text(text, strategy=None, chunk_size=None, overlap=None) -> list[str]:
    strategy = strategy or settings.CHUNK_STRATEGY
    chunk_size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
    overlap = overlap if overlap is not None else settings.CHUNK_OVERLAP

    if overlap >= chunk_size:
        raise ValueError(f"overlap {overlap} must be less than chunk_size {chunk_size}")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    if not text or not text.strip():
        return []

    return [c.strip() for c in STRATEGIES[strategy](text, chunk_size, overlap) if c.strip()]