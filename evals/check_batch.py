"""Do cross-encoder scores change between batched and one-by-one prediction?

    python -m evals.check_batch
"""
from sentence_transformers import CrossEncoder

from app.api.services.retrieval import search_chunks
from app.db.session import SessionLocal

q = "who do I call in an emergency on campus"
db = SessionLocal()
hits = search_chunks(db, q, 20, use_rerank=False)
db.close()

m = CrossEncoder("BAAI/bge-reranker-base")
pairs = [(q, h["text"]) for h in hits]
batched = m.predict(pairs)                                   # all 20 at once
single = [float(m.predict([p])[0]) for p in pairs]           # one at a time

print(f"{'#':>2} {'batched':>9} {'single':>9}  text")
for i, (b, s, h) in enumerate(zip(batched, single, hits), 1):
    print(f"{i:>2} {b:9.4f} {s:9.4f}  {' '.join(h['text'].split())[:70]}")
