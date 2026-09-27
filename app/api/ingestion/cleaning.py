"""Remove page furniture (running headers/footers with page numbers) from extracted text.

PDF extraction keeps every page's footer, e.g.
    "Your University – Handbook for Undergraduate Students /0302 /"
    "04 / Your University – Handbook for Undergraduate Students/05"
Those lines end up inside chunks, where they add noise to embeddings and can
mislead re-rankers.

Rule (deliberately conservative): a line is furniture only if
  (a) it is nothing but a page number, or
  (b) it carries a page number at its start or end AND the rest of the line
      repeats on at least MIN_REPEATS pages.
Repeated lines WITHOUT a page number are kept: PDF extraction splits sentences
into short visual lines, and real content ("Note: students on clinical
programmes") can legitimately repeat.
"""
import re
from collections import Counter

MIN_REPEATS = 5   # footers repeat on most pages; numbered content lines rarely 5+ times
MAX_LINE_CHARS = 120
_SEP = r"[\s/|\-–—]"
_EDGE_NUM = re.compile(rf"^{_SEP}*\d{{1,4}}{_SEP}*|{_SEP}*\d{{1,4}}{_SEP}*$")
_ONLY_NUM = re.compile(rf"^{_SEP}*\d{{1,4}}({_SEP}+\d{{1,4}})*{_SEP}*$")


def _key(line: str) -> str:
    """The line without leading/trailing page numbers, whitespace-normalised."""
    return " ".join(_EDGE_NUM.sub("", line.strip()).lower().split())


def _has_edge_number(line: str) -> bool:
    return bool(_EDGE_NUM.search(line.strip()))


def strip_boilerplate(text: str) -> tuple[str, dict]:
    """Return (cleaned_text, stats). Paragraph breaks are preserved."""
    lines = text.split("\n")
    counts = Counter(_key(l) for l in lines
                     if l.strip() and len(l) <= MAX_LINE_CHARS and _has_edge_number(l))
    kept, removed_footer, removed_pagenum = [], 0, 0
    for line in lines:
        s = line.strip()
        if s and _ONLY_NUM.match(s):
            removed_pagenum += 1
            continue
        if (s and len(line) <= MAX_LINE_CHARS and _has_edge_number(line)
                and _key(line) and counts[_key(line)] >= MIN_REPEATS):
            removed_footer += 1
            continue
        kept.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    stats = {"removed_footer_lines": removed_footer, "removed_page_numbers": removed_pagenum,
             "chars_before": len(text), "chars_after": len(cleaned)}
    return cleaned, stats
