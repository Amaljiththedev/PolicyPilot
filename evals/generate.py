"""Generate eval questions from an ingested document.

    python -m evals.generate --document-id 31 --dry-run     # test on 1 window
    python -m evals.generate --document-id 31               # full run

Works for any format: it reads Document.raw_text (already extracted).
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from openai import OpenAI

from app.core.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal

settings = get_settings()
OUT = Path(__file__).parent / "data" / "synthetic.jsonl"
WINDOW_CHARS = 8_000      # ~2k tokens per window (fits Groq free 6k tokens/min)
MAX_OVERLAP = 0.5         # reject questions that reuse too many of the evidence's words
STOPWORDS = set("a an the is are was were do does did i my me you your to of in on for "
                "and or if can what how when where who which with at by be it this that".split())

client = OpenAI(api_key=settings.LLM_API_KEY or "none", base_url=settings.LLM_BASE_URL)

ANSWERABLE_PROMPT = """You write test questions for a document search system.

From the TEXT below, write {n} questions a real reader might ask, in their own
everyday words. Do NOT reuse the text's exact phrasing. Each question must be
answerable from a single short passage of the TEXT.

Return only JSON: {{"items": [{{"question": "...", "answer": "...",
"evidence": "<an exact, contiguous quote copied from TEXT, 5-30 words>"}}]}}

TEXT:
{text}"""

UNANSWERABLE_PROMPT = """Here are snippets from each section of a document:
{outline}

Write {n} realistic questions on these same general topics that the document
most likely does NOT answer (specific details it would not contain).
Return only JSON: {{"items": [{{"question": "..."}}]}}"""


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def windows(text: str, size: int = WINDOW_CHARS) -> list[str]:
    """Split on paragraph breaks into windows of roughly `size` characters."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) > size and cur:
            out.append(cur)
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur)
    return out


def content_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOPWORDS}


def overlap(question: str, evidence: str) -> float:
    """Share of the question's content words that also appear in the evidence."""
    q = content_words(question)
    return len(q & content_words(evidence)) / len(q) if q else 1.0


def ask(prompt: str) -> list[dict]:
    """Call the LLM, parse JSON, retry with backoff on rate limits or bad output."""
    for attempt in range(4):
        try:
            r = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=4000,
            )
            content = r.choices[0].message.content or ""
            return json.loads(content).get("items", [])
        except Exception as e:
            wait = 10 * (attempt + 1)
            print(f"  retry in {wait}s ({e.__class__.__name__}: {str(e)[:120]})")
            time.sleep(wait)
    return []


def main(document_id: int, per_window: int, n_unanswerable: int, dry_run: bool) -> None:
    db = SessionLocal()
    doc = db.get(Document, document_id)
    if doc is None:
        raise SystemExit(f"document {document_id} not found")

    raw_norm = _norm(doc.raw_text)
    doc_hash = hashlib.sha256(doc.raw_text.encode()).hexdigest()[:16]
    kept, dropped = [], {"fake_evidence": 0, "copied_wording": 0}

    wins = windows(doc.raw_text)
    if dry_run:
        wins = wins[:1]
    print(f"{doc.title}: {len(wins)} window(s), model={settings.LLM_MODEL}")

    for i, w in enumerate(wins):
        for item in ask(ANSWERABLE_PROMPT.format(n=per_window, text=w)):
            q, ev = item.get("question", ""), item.get("evidence", "")
            if not q or not ev or _norm(ev) not in raw_norm:
                dropped["fake_evidence"] += 1
                if dry_run:
                    print(f"  [fake] Q: {q}{chr(10)}         E: {ev}")
                continue
            if overlap(q, ev) > MAX_OVERLAP:
                dropped["copied_wording"] += 1
                if dry_run:
                    print(f"  [copied {overlap(q, ev):.2f}] Q: {q}{chr(10)}         E: {ev}")
                continue
            kept.append({"question": q, "answer": item.get("answer", ""), "evidence": ev,
                         "slice": "simple", "document_id": doc.id, "doc_hash": doc_hash,
                         "window": i, "source": "synthetic", "model": settings.LLM_MODEL})
        print(f"  window {i + 1}/{len(wins)}: {len(kept)} kept, dropped {dropped}")
        time.sleep(15)  # free-tier tokens-per-minute limit

    if not dry_run:
        outline = "\n".join(w[:200].replace("\n", " ") for w in windows(doc.raw_text))
        for item in ask(UNANSWERABLE_PROMPT.format(outline=outline, n=n_unanswerable)):
            if item.get("question"):
                kept.append({"question": item["question"], "answer": "", "evidence": "",
                             "slice": "unanswerable", "document_id": doc.id,
                             "doc_hash": doc_hash, "source": "synthetic",
                             "model": settings.LLM_MODEL})

    if dry_run:
        print("\nDRY RUN - nothing saved. Sample:")
        for k in kept[:4]:
            print(f"  Q: {k['question']}\n  E: {k['evidence']}\n")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as f:
            for k in kept:
                f.write(json.dumps(k, ensure_ascii=False) + "\n")
        print(f"\nsaved {len(kept)} items -> {OUT}  (dropped {dropped})")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--document-id", type=int, required=True)
    p.add_argument("--per-window", type=int, default=6)
    p.add_argument("--unanswerable", type=int, default=5)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    main(a.document_id, a.per_window, a.unanswerable, a.dry_run)
