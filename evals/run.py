"""Run retrieval evals and save a results file.

    python -m evals.run --name baseline
"""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from app.api.services.retrieval import search_chunks
from app.core.config import get_settings
from app.db.session import SessionLocal
from evals.metrics import _norm, first_hit_rank, mrr, ndcg_at_k, recall_at_k

DATA = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"
K = 10


def load_items() -> list[dict]:
    items = []
    gold = DATA / "golden_set.csv"
    if gold.exists():
        with gold.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                items.append({**row, "source": "hand"})
    synth = DATA / "synthetic.jsonl"
    if synth.exists():
        items += [json.loads(line) for line in synth.open(encoding="utf-8") if line.strip()]
    return items


def main(name: str) -> None:
    settings = get_settings()
    db = SessionLocal()
    items = load_items()
    per_item = []

    for it in items:
        hits = search_chunks(db, it["question"], K)
        texts = [h["text"] for h in hits]
        rank = first_hit_rank(texts, it["evidence"]) if it.get("evidence") else None
        # strict = exact quote match only (no 60% word-coverage fallback)
        strict_rank = next((i for i, t in enumerate(texts, 1)
                            if _norm(it["evidence"]) in _norm(t)), None) if it.get("evidence") else None
        ndcg = ndcg_at_k(texts, it["evidence"], 10) if it.get("evidence") else None
        per_item.append({**it, "rank": rank, "strict_rank": strict_rank, "ndcg@10": ndcg,
                         "top_score": hits[0]["score"] if hits else None})
    db.close()

    groups = defaultdict(list)
    for r in per_item:
        groups["ALL (answerable)" if r["slice"] != "unanswerable" else "unanswerable"].append(r)
        groups[f"{r['source']}:{r['slice']}"].append(r)

    report = {}
    for g, rows in sorted(groups.items()):
        if g.endswith("unanswerable"):
            scores = [r["top_score"] for r in rows if r["top_score"] is not None]
            report[g] = {"n": len(rows),
                         "top_score_median": round(median(scores), 4) if scores else None}
        else:
            ranks = [r["rank"] for r in rows]
            report[g] = {"n": len(rows),
                         "recall@1": round(recall_at_k(ranks, 1), 3),
                         "recall@5": round(recall_at_k(ranks, 5), 3),
                         "recall@10": round(recall_at_k(ranks, 10), 3),
                         "mrr": round(mrr(ranks), 3),
                         "ndcg@10": round(mean(r["ndcg@10"] for r in rows), 3),
                         "strict_R@1": round(recall_at_k([r["strict_rank"] for r in rows], 1), 3),
                         "strict_R@5": round(recall_at_k([r["strict_rank"] for r in rows], 5), 3)}

    answerable_top = [r["top_score"] for r in per_item
                      if r["slice"] != "unanswerable" and r["top_score"] is not None]
    if answerable_top:
        report["ALL (answerable)"]["top_score_median"] = round(median(answerable_top), 4)

    print(f"\n{'group':<28}{'n':>4}{'R@1':>7}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'sR@1':>7}{'sR@5':>7}{'top_sc':>8}")
    for g, m in report.items():
        print(f"{g:<28}{m['n']:>4}{m.get('recall@1', ''):>7}{m.get('recall@5', ''):>7}"
              f"{m.get('recall@10', ''):>7}{m.get('mrr', ''):>7}{m.get('ndcg@10', ''):>7}{m.get('strict_R@1', ''):>7}"
              f"{m.get('strict_R@5', ''):>7}{m.get('top_score_median', ''):>8}")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out = RESULTS / f"{name}_{stamp}.json"
    out.write_text(json.dumps({
        "name": name, "created": stamp,
        "config": {"chunk_size": settings.CHUNK_SIZE, "chunk_overlap": settings.CHUNK_OVERLAP,
                   "strategy": settings.CHUNK_STRATEGY, "model": settings.EMBEDDING_MODEL, "k": K},
        "metrics": report,
        "items": per_item,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="baseline")
    main(p.parse_args().name)