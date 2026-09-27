"""Run retrieval evals and save a results file.

    python -m evals.run --name baseline
"""
import argparse
import csv
import json
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

from app.api.services.retrieval import search_chunks
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.api.services.reranker import STRATEGIES
from evals.metrics import _norm, first_hit_rank, mrr, ndcg_at_k, recall_at_k

DATA = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"
K = 10


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% interval for the mean: resample the questions with replacement n times."""
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(n))
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n)], 3)


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


def main(name: str, rerank_strategy: str | None = None,
         rerank_model: str | None = None, candidates: int | None = None,
         search_mode: str | None = None) -> None:
    settings = get_settings()
    # command-line overrides, so experiments don't need .env edits
    if rerank_model:
        settings.RERANK_MODEL = rerank_model
    if candidates:
        settings.RERANK_CANDIDATES = candidates
        settings.LLM_RERANK_CANDIDATES = candidates
    if search_mode:
        settings.SEARCH_MODE = search_mode
    db = SessionLocal()
    items = load_items()
    per_item = []

    for it in items:
        t0 = time.perf_counter()
        hits = search_chunks(db, it["question"], K,
                             use_rerank=rerank_strategy is not None,
                             strategy=rerank_strategy, mode=search_mode)
        latency_ms = (time.perf_counter() - t0) * 1000
        print(f"  {len(per_item) + 1}/{len(items)}  {latency_ms:6.0f} ms  {it['question'][:50]}", flush=True)
        texts = [h["text"] for h in hits]
        rank = first_hit_rank(texts, it["evidence"]) if it.get("evidence") else None
        # strict = exact quote match only (no 60% word-coverage fallback)
        strict_rank = next((i for i, t in enumerate(texts, 1)
                            if _norm(it["evidence"]) in _norm(t)), None) if it.get("evidence") else None
        ndcg = ndcg_at_k(texts, it["evidence"], 10) if it.get("evidence") else None
        per_item.append({**it, "rank": rank, "strict_rank": strict_rank, "ndcg@10": ndcg,
                         "top_score": hits[0]["score"] if hits else None,
                         "latency_ms": round(latency_ms)})
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

    ans = [r for r in per_item if r["slice"] != "unanswerable"]
    rr = [1 / r["rank"] if r["rank"] else 0.0 for r in ans]
    r1 = [1.0 if r["rank"] == 1 else 0.0 for r in ans]
    report["ALL (answerable)"]["mrr_95ci"] = bootstrap_ci(rr)
    report["ALL (answerable)"]["recall@1_95ci"] = bootstrap_ci(r1)
    report["ALL (answerable)"]["ndcg@10_95ci"] = bootstrap_ci([r["ndcg@10"] for r in ans])

    answerable_top = [r["top_score"] for r in per_item
                      if r["slice"] != "unanswerable" and r["top_score"] is not None]
    if answerable_top:
        report["ALL (answerable)"]["top_score_median"] = round(median(answerable_top), 4)

    print(f"\n{'group':<28}{'n':>4}{'R@1':>7}{'R@5':>7}{'R@10':>7}{'MRR':>7}{'nDCG':>7}{'sR@1':>7}{'sR@5':>7}{'top_sc':>8}")
    for g, m in report.items():
        print(f"{g:<28}{m['n']:>4}{m.get('recall@1', ''):>7}{m.get('recall@5', ''):>7}"
              f"{m.get('recall@10', ''):>7}{m.get('mrr', ''):>7}{m.get('ndcg@10', ''):>7}{m.get('strict_R@1', ''):>7}"
              f"{m.get('strict_R@5', ''):>7}{m.get('top_score_median', ''):>8}")

    a = report["ALL (answerable)"]
    print(f"\n95% CI (bootstrap, {a['n']} q): MRR {a['mrr']} {a['mrr_95ci']}  "
          f"R@1 {a['recall@1']} {a['recall@1_95ci']}  nDCG {a['ndcg@10']} {a['ndcg@10_95ci']}")

    from app.api.services.llm import STATS as llm_stats
    if llm_stats["calls"]:
        rate = llm_stats["failed"] / llm_stats["calls"]
        print(f"\nLLM calls: {llm_stats['calls']}, ok {llm_stats['ok']}, failed {llm_stats['failed']} ({rate:.0%})")
        if rate > 0.2:
            print(f"WARNING: over 20% of LLM calls failed; these results mostly reflect the fallback order, not the LLM."
                  f" Last error: {llm_stats['last_error']}")
    lat = [r["latency_ms"] for r in per_item]
    print(f"\nlatency per question: median {median(lat):.0f} ms, max {max(lat):.0f} ms")

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    out = RESULTS / f"{name}_{stamp}.json"
    out.write_text(json.dumps({
        "name": name, "created": stamp,
        "config": {"chunk_size": settings.CHUNK_SIZE, "chunk_overlap": settings.CHUNK_OVERLAP,
                   "strategy": settings.CHUNK_STRATEGY, "model": settings.EMBEDDING_MODEL, "k": K,
                   "search_mode": settings.SEARCH_MODE,
                   "rerank_strategy": rerank_strategy,
                   "llm_model": settings.LLM_MODEL if (rerank_strategy or "").startswith("llm") else None,
                   "llm_stats": __import__("app.api.services.llm", fromlist=["STATS"]).STATS if (rerank_strategy or "").startswith("llm") else None,
                   "rerank_model": settings.RERANK_MODEL if rerank_strategy and rerank_strategy.startswith("cross") else None,
                   "rerank_candidates": (settings.RERANK_CANDIDATES if (rerank_strategy or "").startswith("cross")
                                         else settings.LLM_RERANK_CANDIDATES) if rerank_strategy else None},
        "metrics": report,
        "items": per_item,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="baseline")
    p.add_argument("--rerank-strategy", choices=STRATEGIES, default=None)
    p.add_argument("--rerank-model", default=None, help="override RERANK_MODEL, e.g. cross-encoder/ms-marco-MiniLM-L-6-v2")
    p.add_argument("--search-mode", choices=("vector", "keyword", "hybrid"), default=None)
    p.add_argument("--candidates", type=int, default=None, help="how many chunks the re-ranker sees")
    args = p.parse_args()
    main(args.name, rerank_strategy=args.rerank_strategy,
         rerank_model=args.rerank_model, candidates=args.candidates,
         search_mode=args.search_mode)