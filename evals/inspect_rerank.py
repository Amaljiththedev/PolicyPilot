"""Show the top 3 chunks with and without re-ranking for a few questions.

    python -m evals.inspect_rerank
"""
from app.api.services.retrieval import search_chunks
from app.db.session import SessionLocal

QUESTIONS = [
    "can I use ChatGPT to write my assignment",
    "is there a cheap bus home late at night",
    "who do I call in an emergency on campus",
]

db = SessionLocal()
for q in QUESTIONS:
    print("\n" + "=" * 90 + f"\nQ: {q}")
    for label, rr in [("VECTOR", False), ("RERANK", True)]:
        print(f"\n  --- {label} ---")
        for i, h in enumerate(search_chunks(db, q, 3, use_rerank=rr, strategy="cross"), 1):
            text = " ".join(h["text"].split())[:220]
            print(f"  {i}. [{h['score']}] {text}")
db.close()
