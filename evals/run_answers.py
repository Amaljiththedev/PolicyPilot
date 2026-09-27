"""Phase 8.5: answer-quality evals over the golden set.

    python -m evals.run_answers --name answers_v2
    python -m evals.run_answers --name answers_v1 --prompt v1
    python -m evals.run_answers --name quick --limit 5          # smoke test

Per question it runs the real answer pipeline (search -> LLM -> citation check), then:
  refusal     answerable questions answered? unanswerable ones refused?      (code)
  citation    does a CITED passage contain the golden evidence?              (code)
  retrieval   did ANY passage shown to the model contain it?                 (code)
  judge       a different LLM checks each claim against the cited passages,
              grades correctness vs the evidence, and (conditional slice)
              whether the condition/qualifier was kept                       (LLM)
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from app.api.services.answer import answer_question
from app.api.services.llm import STATS, chat_json
from app.core.config import get_settings
from app.db.session import SessionLocal
from evals.metrics import is_hit
from evals.run import bootstrap_ci

DATA = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"

JUDGE_PROMPT = """You are grading an answer produced by a policy assistant.

Question: {question}

Passages the answer cites:
{passages}

Answer:
{answer}

Reference evidence (the correct source text): {evidence}
Question type: {slice}

Do three things:
1. Split the answer into its factual claims. For each, "supported" is true only if the
   cited passages state it (a claim that is stronger or broader than the passage, or drops
   a qualifier such as "normally" or "only if", is NOT supported).
2. "correctness": "correct" if the answer matches the reference evidence, "partial" if it is
   incomplete or slightly off, "wrong" if it contradicts or misses it.
3. "condition_kept": for type "conditional" only, true if the answer states the condition or
   qualifier the reference evidence depends on; otherwise null.

Return JSON only:
{{"claims": [{{"claim": "...", "supported": true}}], "correctness": "correct|partial|wrong",
  "condition_kept": true, "note": "one short sentence"}}"""


def load_golden() -> list[dict]:
    with (DATA / "golden_set.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def judge(item: dict, res: dict, judge_model: str) -> dict:
    cited = [s for s in res["sources"] if s["n"] in res["citations"]]
    passages = "\n\n".join(f"[{s['n']}] {s['text']}" for s in cited) or "(none)"
    try:
        return chat_json(JUDGE_PROMPT.format(question=item["question"], passages=passages,
                                             answer=res["answer"], evidence=item["evidence"],
                                             slice=item["slice"]),
                         max_tokens=600, model=judge_model)   # small: Groq caps output tokens/min per model
    except RuntimeError as e:
        return {"error": str(e)}


def main(name: str, prompt: str | None, top_k: int | None, limit: int | None, no_judge: bool,
         only: str | None = None):
    s = get_settings()
    prompt = prompt or s.ANSWER_PROMPT
    items = load_golden()
    if only:
        items = [it for it in items if only.lower() in it["question"].lower()]
    items = items[:limit] if limit else items
    db = SessionLocal()
    # checkpoint: every finished question is appended here, so a crash or the daily
    # rate limit doesn't throw away 20 minutes of work. Re-run the same --name to resume.
    RESULTS.mkdir(exist_ok=True)
    ckpt = RESULTS / f"{name}.partial.jsonl"
    done_q = {}
    if ckpt.exists():
        for line in ckpt.open(encoding="utf-8"):
            r = json.loads(line)
            if "error" not in r:
                done_q[r["question"]] = r
        # drop saved rows whose label changed since they were run (e.g. relabelled
        # unanswerable -> answerable): their scores would be computed against the old label
        current = {it["question"]: it for it in items}
        stale = [q for q, r in done_q.items()
                 if q in current and (r.get("slice"), r.get("evidence") or "") !=
                 (current[q]["slice"], current[q]["evidence"] or "")]
        for q in stale:
            del done_q[q]
        if stale:
            print(f"re-running {len(stale)} question(s) whose label changed: {stale}")
        print(f"resuming: {len(done_q)} questions already done in {ckpt.name}")
    rows = []
    for i, it in enumerate(items, 1):
        answerable = it["slice"] != "unanswerable"
        if it["question"] in done_q:
            rows.append(done_q[it["question"]])
            continue
        try:
            res = answer_question(db, it["question"], top_k, prompt_version=prompt)
        except RuntimeError as e:
            print(f"  {i}/{len(items)}  LLM FAILED  {it['question'][:50]}  ({e})", flush=True)
            rows.append({**it, "error": str(e)})
            if "per day" in str(e):
                print("\nDaily token limit reached. Progress is saved; re-run the same command "
                      "after the limit resets (or switch LLM_MODEL) to continue.")
                break
            continue

        row = {**it, "answer": res["answer"], "answered": res["answerable"],
               "reason": res["reason"], "citations": res["citations"],
               "latency_ms": res["latency_ms"]}
        if answerable and res["answerable"]:
            cited_txt = [x["text"] for x in res["sources"] if x["n"] in res["citations"]]
            row["citation_hit"] = any(is_hit(t, it["evidence"]) for t in cited_txt)
            row["inline_citation"] = "[" in res["answer"]
            if not no_judge:
                j = judge(it, res, s.JUDGE_MODEL)
                row["judge"] = j
                claims = j.get("claims") or []
                if claims:
                    row["faithfulness"] = mean(1.0 if c.get("supported") else 0.0 for c in claims)
                row["correctness"] = j.get("correctness")
                row["condition_kept"] = j.get("condition_kept") if it["slice"] == "conditional" else None
        if answerable:
            row["retrieval_hit"] = any(is_hit(x["text"], it["evidence"]) for x in res["sources"])

        flag = ("ANSWERED" if res["answerable"] else "refused ")
        ok = (res["answerable"] == answerable)
        print(f"  {i}/{len(items)}  {'ok ' if ok else 'BAD'} {flag} {row.get('correctness') or '':8}"
              f" faith={row.get('faithfulness', '-')!s:5.4}  {it['question'][:48]}", flush=True)
        rows.append(row)
        with ckpt.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    db.close()

    done = [r for r in rows if "error" not in r]
    ans = [r for r in done if r["slice"] != "unanswerable"]
    una = [r for r in done if r["slice"] == "unanswerable"]
    answered = [r for r in ans if r["answered"]]
    faith = [r["faithfulness"] for r in answered if "faithfulness" in r]
    cond = [r["condition_kept"] for r in answered if r.get("condition_kept") is not None]
    corr = [r.get("correctness") for r in answered if r.get("correctness")]

    m = {
        "n": len(items), "llm_errors": len(rows) - len(done),
        "unanswerable_refused": f"{sum(not r['answered'] for r in una)}/{len(una)}",
        "false_refusals": f"{sum(not r['answered'] for r in ans)}/{len(ans)}",
        "false_refusals_with_evidence_retrieved":
            sum((not r["answered"]) and r.get("retrieval_hit") for r in ans),
        "citation_accuracy": round(mean(r["citation_hit"] for r in answered), 3) if answered else None,
        "inline_citations": round(mean(r["inline_citation"] for r in answered), 3) if answered else None,
        "faithfulness": round(mean(faith), 3) if faith else None,
        "faithfulness_95ci": bootstrap_ci(faith) if len(faith) > 1 else None,
        "fully_faithful_answers": f"{sum(f == 1.0 for f in faith)}/{len(faith)}",
        "correct": corr.count("correct"), "partial": corr.count("partial"), "wrong": corr.count("wrong"),
        "condition_kept": f"{sum(bool(c) for c in cond)}/{len(cond)}" if cond else None,
        "latency_ms_median": sorted(r["latency_ms"] for r in done)[len(done) // 2] if done else None,
    }

    print("\n==== answer eval:", name, f"(prompt {prompt}, answer model {s.LLM_MODEL}, judge {s.JUDGE_MODEL})")
    for k, v in m.items():
        print(f"  {k:<40}{v}")
    gates = {
        "all unanswerable refused": all(not r["answered"] for r in una) if una else None,
        "false refusals <= 2": sum(not r["answered"] for r in ans) <= 2,
        "faithfulness >= 0.9": (m["faithfulness"] or 0) >= 0.9,
        "citation accuracy >= 0.9": (m["citation_accuracy"] or 0) >= 0.9,
    }
    print("\n  GATE")
    for g, ok in gates.items():
        print(f"    [{'n/a ' if ok is None else 'PASS' if ok else 'FAIL'}] {g}")
    print(f"\n  LLM calls {STATS['calls']}, failed {STATS['failed']}")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{name}_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps({"name": name, "kind": "answers",
                               "config": {"prompt": prompt, "answer_model": s.LLM_MODEL,
                                          "judge_model": s.JUDGE_MODEL,
                                          "top_k": top_k or s.ANSWER_TOP_K,
                                          "rerank": s.RERANK_STRATEGY if s.RERANK_ENABLED else None},
                               "metrics": m, "gates": gates, "items": rows},
                              indent=2, default=str), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="answers")
    p.add_argument("--prompt", choices=("v1", "v2", "v3"), default=None)
    p.add_argument("--top-k", type=int, default=None)
    p.add_argument("--limit", type=int, default=None, help="only the first N questions (smoke test)")
    p.add_argument("--only", default=None, help="only questions containing this text, e.g. \"doctor\"")
    p.add_argument("--no-judge", action="store_true", help="skip the LLM judge (half the calls)")
    a = p.parse_args()
    main(a.name, a.prompt, a.top_k, a.limit, a.no_judge, a.only)
