"""Extract plain text from uploaded documents.

One public function: extract_text(content, content_type, filename=None).
Each format has a private handler; PARSERS maps content types to them, so
adding a format is a function plus a dict entry.
"""
import re
from io import BytesIO

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from pypdf import PdfReader

# Below this many characters we treat the document as unreadable rather than
# empty-but-valid. A scanned PDF parses fine and yields nothing.
MIN_USABLE_CHARS = 50

# Tags whose text is chrome, not content.
HTML_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "noscript", "form")


class UnsupportedFileType(Exception):
    """No parser registered for this content type."""
    


class EmptyDocument(Exception):
    """Parsed without error but produced no usable text."""


class CorruptDocument(Exception):
    """File is malformed, encrypted, or otherwise unreadable."""


def _normalise(text: str) -> str:
    """Tidy whitespace without destroying paragraph structure.

    Paragraph breaks survive because structure-aware chunking needs them
    later; everything else collapses.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)           # runs of spaces -> one
    text = re.sub(r" *\n *", "\n", text)          # strip space around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)        # 3+ blank lines -> one break
    return text.strip()


def _from_txt(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        # latin-1 maps every byte to a character, so this cannot raise.
        # Some characters may be wrong, which beats rejecting the file.
        return content.decode("latin-1")


def _from_pdf(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            # An empty password unlocks many "encrypted" PDFs.
            if reader.decrypt("") == 0:
                raise CorruptDocument("PDF is password protected")
        # extract_text() returns None for pages with no text layer.
        pages = [page.extract_text() or "" for page in reader.pages]
    except CorruptDocument:
        raise
    except Exception as exc:
        raise CorruptDocument(f"could not read PDF: {exc}") from exc
    return "\n\n".join(pages)


def _from_docx(content: bytes) -> str:
    try:
        doc = DocxDocument(BytesIO(content))
    except Exception as exc:
        raise CorruptDocument(f"could not read DOCX: {exc}") from exc

    parts = [p.text for p in doc.paragraphs if p.text.strip()]

    # Table text lives outside doc.paragraphs. In a policy document that is
    # usually where the numbers are, so dropping it would be quietly wrong.
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n\n".join(parts)


def _from_html(content: bytes) -> str:
    soup = BeautifulSoup(_from_txt(content), "html.parser")
    for tag in soup(HTML_NOISE_TAGS):
        tag.decompose()
    return soup.get_text(separator="\n")


PARSERS = {
    "text/plain": _from_txt,
    "text/markdown": _from_txt,
    "application/pdf": _from_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _from_docx,
    "text/html": _from_html,
}

# Browsers and curl often send application/octet-stream or get the type wrong,
# so fall back to the filename extension.
EXTENSIONS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
}


def _resolve(content_type: str, filename: str | None) -> str:
    base = (content_type or "").split(";")[0].strip().lower()
    if base in PARSERS:
        return base
    if filename:
        ext = filename[filename.rfind("."):].lower() if "." in filename else ""
        if ext in EXTENSIONS:
            return EXTENSIONS[ext]
    raise UnsupportedFileType(content_type or filename or "unknown")


def extract_text(content: bytes, content_type: str, filename: str | None = None) -> str:
    """Return the document's text.

    Raises UnsupportedFileType, CorruptDocument, or EmptyDocument.
    """
    if not content:
        raise EmptyDocument("file is empty")

    resolved = _resolve(content_type, filename)
    text = _normalise(PARSERS[resolved](content))

    if len(text) < MIN_USABLE_CHARS:
        raise EmptyDocument(
            f"{resolved} produced {len(text)} characters; "
            "the file may be scanned images or otherwise have no text layer"
        )
    return text