"""Check every golden-set evidence quote really appears in its document,
using the SAME parser the app uses (so PDF extraction quirks are caught).

    python -m evals.check_golden

Documents come from corpus/; the doc column maps to a file below.
"""
import csv
from pathlib import Path

from app.api.ingestion.parser import extract_text
from evals.metrics import _norm

ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "uol_handbook": "corpus/uol_student_handbook_2025.pdf",
    "faversham_hr": "corpus/faversham_tc_employee_handbook_2024.pdf",
    "edc_ict_aup": "corpus/east_dunbartonshire_ict_acceptable_use_policy.pdf",
}
TYPES = {".pdf": "application/pdf", ".html": "text/html", ".txt": "text/plain"}

texts = {}
for key, rel in DOCS.items():
    f = ROOT / rel
    if f.exists():
        texts[key] = _norm(extract_text(f.read_bytes(), TYPES[f.suffix], f.name))
    else:
        print(f"(skip {key}: {rel} not found)")

bad = 0
skipped = 0
counts = {}
for r in csv.DictReader((ROOT / "evals/data/golden_set.csv").open(encoding="utf-8")):
    counts[(r["doc"], r["slice"])] = counts.get((r["doc"], r["slice"]), 0) + 1
    if r["slice"] == "unanswerable":
        continue
    if r["doc"] not in texts:
        skipped += 1
        continue
    if _norm(r["evidence"]) not in texts[r["doc"]]:
        bad += 1
        print(f"MISSING [{r['doc']}] {r['question']!r}\n   evidence: {r['evidence']!r}")

print("\nquestions per doc/slice:")
for (d, s), n in sorted(counts.items()):
    print(f"  {d:<14}{s:<14}{n}")
checked = sum(n for (d, s_), n in counts.items() if s_ != "unanswerable") - skipped
print(f"\nchecked {checked}, skipped {skipped} (document file missing)")
if not checked:
    raise SystemExit("nothing was checked: is corpus/ visible inside the container?")
print(f"{bad} evidence quotes not found" if bad else "all checked evidence quotes found")
