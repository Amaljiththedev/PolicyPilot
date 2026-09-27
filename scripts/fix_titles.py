"""Re-title existing documents from their filename (one-off).

    python scripts/fix_titles.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.api.ingestion.titles import clean_title
from app.db.models import Document
from app.db.session import SessionLocal

db = SessionLocal()
for d in db.query(Document).all():
    new = clean_title(d.filename)
    if new != d.title:
        print(f"{d.id}: {d.title!r} -> {new!r}")
        d.title = new
db.commit()
db.close()
