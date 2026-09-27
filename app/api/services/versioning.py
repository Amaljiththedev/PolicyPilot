"""Phase 9: policy versions.

Every document belongs to a policy (policy_key). Uploading a new version of a policy
marks the old one is_current=False, so search only sees the latest rules, while the
old text stays in the database for audit and for "what changed?".
"""
import difflib
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Document


def slugify(text: str | None) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "untitled").lower()).strip("-")
    return s[:120] or "untitled"


def attach_version(db: Session, doc: Document, policy_key: str) -> Document | None:
    """Make `doc` the newest version of `policy_key`. Returns the version it replaced, if any.
    Call after db.add(doc) + flush, inside the same transaction as the upload."""
    doc.policy_key = policy_key
    previous = (db.query(Document)
                .filter(Document.policy_key == policy_key, Document.id != doc.id,
                        Document.is_current.is_(True))
                .order_by(Document.version.desc())
                .first())
    top = (db.query(func.max(Document.version))
           .filter(Document.policy_key == policy_key, Document.id != doc.id).scalar())
    doc.version = (top or 0) + 1
    doc.is_current = True
    if previous is not None:
        previous.is_current = False
        doc.supersedes_id = previous.id
        if doc.organisation is None:          # a new version belongs to the same organisation
            doc.organisation = previous.organisation
    return previous


def _units(text: str) -> list[str]:
    """Split into sentence-sized units, whitespace-normalised, so a re-flowed PDF line
    break doesn't count as a change."""
    flat = " ".join(text.split())
    return [u.strip() for u in re.split(r"(?<=[.;:!?])\s+", flat) if u.strip()]


def diff_texts(old: str, new: str, max_items: int = 50) -> list[dict]:
    """Sentence-level changes between two versions: changed / added / removed."""
    a, b = _units(old), _units(new)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            # same number of sentences on both sides: report each edited sentence on its own
            pairs = [{"type": "changed", "old": a[i], "new": b[j]}
                     for i, j in zip(range(i1, i2), range(j1, j2))]
        else:
            kind = {"replace": "changed", "insert": "added", "delete": "removed"}[tag]
            pairs = [{"type": kind, "old": " ".join(a[i1:i2]) or None,
                      "new": " ".join(b[j1:j2]) or None}]
        out.extend(pairs)
        if len(out) >= max_items:
            return out[:max_items]
    return out
