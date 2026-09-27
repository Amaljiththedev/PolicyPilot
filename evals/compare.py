"""Is config B really better than A? Paired bootstrap over the same questions.

    python -m evals.compare evals/results/baseline_X.json evals/results/hybrid_Y.json

Resamples questions (keeping each question's A and B scores together) and reports the
95% interval of the difference. If the interval includes 0, the gain may be noise.
"""
import json
import random
import sys
from statistics import mean


def per_q(path):
    d = json.load(open(path, encoding="utf-8"))
    out = {}
    for r in d["items"]:
        if r.get("slice") == "unanswerable":
            continue
        out[r["question"]] = {"mrr": 1 / r["rank"] if r["rank"] else 0.0,
                              "r@1": 1.0 if r["rank"] == 1 else 0.0,
                              "ndcg": r["ndcg@10"] or 0.0}
    return d["name"], out


def main(a_path, b_path, n=5000):
    an, a = per_q(a_path)
    bn, b = per_q(b_path)
    qs = sorted(set(a) & set(b))
    rng = random.Random(0)
    print(f"{an}  vs  {bn}   ({len(qs)} shared questions)\n")
    print(f"{'metric':<7}{'A':>7}{'B':>7}{'B-A':>8}   95% CI of B-A      P(B>A)")
    for m in ("mrr", "r@1", "ndcg"):
        diffs = [b[q][m] - a[q][m] for q in qs]
        boots = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
        lo, hi = boots[int(.025 * n)], boots[int(.975 * n)]
        p = sum(x > 0 for x in boots) / n
        verdict = "real" if lo > 0 else ("worse" if hi < 0 else "noise")
        print(f"{m:<7}{mean(a[q][m] for q in qs):>7.3f}{mean(b[q][m] for q in qs):>7.3f}"
              f"{mean(diffs):>+8.3f}   [{lo:+.3f}, {hi:+.3f}]   {p:5.0%}  {verdict}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
