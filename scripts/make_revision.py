"""Phase 9 eval fixture: create a realistic "2025 revision" of an uploaded policy and
ingest it as the NEW VERSION of that policy (the old one becomes superseded).

    python scripts/make_revision.py --document-id 32

Each edit changes one rule. The golden set's `superseded` slice asks about exactly these
rules: the new wording must be retrieved, and the old wording must NOT be.
The revised text is saved to evals/data/revisions/ for the record.
"""
import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.api.services.ingest import ingest_bytes
from app.db.models import Document
from app.db.session import SessionLocal

# (old wording, new wording). Matching ignores line breaks inside the phrase.
EDITS = [
    ("at least 4 weeks in advance", "at least 2 weeks in advance"),
    ("You may carry forward up to 5 days", "You may carry forward up to 10 days"),
    ("by no later than 12 noon", "by no later than 10am"),
    ("Paternity leave is payable at the statutory rate", "Paternity leave is paid at full pay for both weeks"),
]
OUT = Path(__file__).resolve().parent.parent / "evals" / "data" / "revisions"


def apply_edits(text: str) -> str:
    for old, new in EDITS:
        pattern = r"\s+".join(map(re.escape, old.split()))
        text, n = re.subn(pattern, new, text)
        if n == 0:
            raise SystemExit(f"edit not applied, wording not found: {old!r}")
        print(f"  {n}x  {old!r} -> {new!r}")
    return text


def main(doc_id: int, effective: date):
    db = SessionLocal()
    doc = db.get(Document, doc_id)
    if doc is None:
        raise SystemExit(f"document {doc_id} not found")
    if not doc.is_current:
        raise SystemExit(f"document {doc_id} is already superseded")
    print(f"revising document {doc_id} ({doc.title}), policy_key={doc.policy_key}, v{doc.version}")
    new_text = apply_edits(doc.raw_text)

    OUT.mkdir(parents=True, exist_ok=True)
    name = f"{doc.policy_key}-revision-{effective.isoformat()}.txt"
    (OUT / name).write_text(new_text, encoding="utf-8")

    new = ingest_bytes(db, new_text.encode("utf-8"), name, "text/plain", doc.uploaded_by,
                       text=new_text, title=f"{doc.title} (revised {effective.isoformat()})",
                       policy_key=doc.policy_key, effective_date=effective)
    print(f"new version: document {new.id}, v{new.version}, supersedes {new.supersedes_id}")
    print(f"see what changed:  GET /api/v1/documents/{new.id}/changes")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--document-id", type=int, required=True)
    p.add_argument("--effective", type=date.fromisoformat, default=date(2025, 4, 1))
    a = p.parse_args()
    main(a.document_id, a.effective)
