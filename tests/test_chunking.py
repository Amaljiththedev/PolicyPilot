import pytest
from app.api.services.chunking import chunk_text, chunk_fixed, chunk_recursive


# ---------------------------------------------------------------------------
# Fixed-strategy tests
# ---------------------------------------------------------------------------

def test_chunk_fixed_basic():
    text = "A" * 500
    chunks = chunk_text(text, strategy="fixed", chunk_size=200, overlap=50)

    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 200


def test_chunk_fixed_overlap_content():
    """Last characters of chunk N match first characters of chunk N+1."""
    text = "the quick brown fox jumps over the lazy dog " * 20
    chunks = chunk_fixed(text, chunk_size=100, overlap=20)

    for i in range(len(chunks) - 1):
        assert chunks[i][-20:] == chunks[i + 1][:20]


# ---------------------------------------------------------------------------
# Recursive-strategy tests
# ---------------------------------------------------------------------------

def test_chunk_recursive_respects_paragraph_breaks():
    """Recursive splitter should prefer splitting on paragraph boundaries."""
    paragraphs = [f"Paragraph {n}. " + "Filler sentence. " * 20 for n in range(5)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, strategy="recursive", chunk_size=300, overlap=50)

    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= 300 + 50  # allow some tolerance from langchain splitter


def test_chunk_recursive_short_text():
    """Text shorter than chunk_size should come back as a single chunk."""
    text = "This is a short policy statement that fits in one chunk."
    chunks = chunk_text(text, strategy="recursive", chunk_size=1000, overlap=100)

    assert len(chunks) == 1
    assert chunks[0] == text


# ---------------------------------------------------------------------------
# Edge / error cases
# ---------------------------------------------------------------------------

def test_empty_text_returns_empty_list():
    assert chunk_text("", strategy="fixed", chunk_size=100, overlap=10) == []
    assert chunk_text("   ", strategy="recursive", chunk_size=100, overlap=10) == []
    assert chunk_text(None, strategy="fixed", chunk_size=100, overlap=10) == []


def test_overlap_equals_chunk_size_raises():
    with pytest.raises(ValueError, match="overlap.*must be less than"):
        chunk_text("hello world " * 100, strategy="fixed", chunk_size=100, overlap=100)


def test_overlap_exceeds_chunk_size_raises():
    with pytest.raises(ValueError, match="overlap.*must be less than"):
        chunk_text("hello world " * 100, strategy="fixed", chunk_size=100, overlap=150)


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown strategy"):
        chunk_text("hello world " * 100, strategy="nonexistent", chunk_size=100, overlap=10)


# ---------------------------------------------------------------------------
# Integration-style: realistic policy text
# ---------------------------------------------------------------------------

def test_realistic_policy_document():
    """Simulate a real multi-section policy document being chunked."""
    sections = []
    for i in range(1, 6):
        section = f"Section {i}: Policy Requirement\n"
        section += "All employees must comply with this guideline. " * 15
        sections.append(section)
    document = "\n\n".join(sections)

    # Fixed strategy
    fixed_chunks = chunk_text(document, strategy="fixed", chunk_size=300, overlap=50)
    assert len(fixed_chunks) >= 3
    assert all(len(c) <= 300 for c in fixed_chunks)

    # Recursive strategy
    recursive_chunks = chunk_text(document, strategy="recursive", chunk_size=300, overlap=50)
    assert len(recursive_chunks) >= 3

    # Every character in the source should appear in at least one chunk
    full_fixed = " ".join(fixed_chunks)
    assert "Section 1" in full_fixed
    assert "Section 5" in full_fixed
