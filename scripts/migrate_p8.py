"""Add Phase 8 columns to the existing queries table (create_all never alters tables).

    python scripts/migrate_p8.py

Safe to run twice: every statement uses IF NOT EXISTS.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text

from app.db.session import engine

COLUMNS = {
    "source_chunk_ids": "JSON",
    "cited_chunk_ids": "JSON",
    "answerable": "BOOLEAN",
    "escalated": "BOOLEAN NOT NULL DEFAULT FALSE",
    "refusal_reason": "VARCHAR(64)",
    "latency_ms": "INTEGER",
    "model": "VARCHAR(100)",
}

with engine.begin() as conn:
    for name, sqltype in COLUMNS.items():
        conn.execute(text(f"ALTER TABLE queries ADD COLUMN IF NOT EXISTS {name} {sqltype}"))
        print(f"queries.{name} ok")
print("done")
