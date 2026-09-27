"""Phase 9 columns on documents (versions + organisation). Safe to run twice.

    python scripts/migrate_p9.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text

from app.api.services.versioning import slugify
from app.db.session import engine

COLUMNS = {
    "policy_key": "VARCHAR(120)",
    "version": "INTEGER NOT NULL DEFAULT 1",
    "is_current": "BOOLEAN NOT NULL DEFAULT TRUE",
    "supersedes_id": "INTEGER REFERENCES documents(id) ON DELETE SET NULL",
    "effective_date": "DATE",
    "organisation": "VARCHAR(120)",
}

with engine.begin() as conn:
    for name, sqltype in COLUMNS.items():
        conn.execute(text(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {name} {sqltype}"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_policy_key ON documents (policy_key)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_is_current ON documents (is_current)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_organisation ON documents (organisation)"))
    # backfill: every existing document becomes version 1 of its own policy
    rows = conn.execute(text("SELECT id, title FROM documents WHERE policy_key IS NULL")).all()
    for doc_id, title in rows:
        conn.execute(text("UPDATE documents SET policy_key = :k WHERE id = :i"),
                     {"k": slugify(title), "i": doc_id})
    print(f"documents: columns ok, backfilled policy_key on {len(rows)} rows")
