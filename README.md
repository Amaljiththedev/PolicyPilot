# PolicyPilot

Question answering over policy documents, with citations, an honest "I don't know", and an evaluation harness that measures every change.

> **Status:** in development. Ingestion, search and the retrieval eval harness are built and tested. Re-ranking experiments are in progress. Answer generation (`/ask`), policy versioning, Google Drive sync and the Slack bot are planned.

---

## Why this exists

Organisations keep their rules in long documents that almost nobody reads end to end. The same questions get asked again and again, answered inconsistently, and often answered from a version of the policy that was replaced months ago.

A general chatbot doesn't fix that. It has never seen the documents, and when it is given them it will still produce a confident answer when the documents say nothing. PolicyPilot is built around two rules:

1. Every answer must point to the passage it came from.
2. When the documents don't contain the answer, the system says so.

The third rule is about the engineering: **quality is shown with numbers, not claims.** Every retrieval change in this repo is measured against a fixed baseline before it is kept.

---

## Architecture

```mermaid
flowchart LR
  subgraph Ingest["Write path (once per document)"]
    U[POST /documents] --> V{Validate<br/>type, size, SHA-256 dup}
    V --> P[Parse<br/>PDF, DOCX, HTML, TXT]
    P --> C[Chunk<br/>recursive, 1000 / 200]
    C --> E[Embed<br/>bge-small-en-v1.5, 384-d]
    E --> DB[(PostgreSQL + pgvector<br/>HNSW cosine index)]
  end

  subgraph Read["Read path (once per question)"]
    Q[POST /search] --> QE[Embed query<br/>with BGE prefix]
    QE --> VS[Vector search<br/>top k or top 20]
    VS --> RR{Re-rank?<br/>cross / llm_point / llm_list}
    RR --> R[Ranked chunks + scores]
  end

  DB --> VS

  subgraph Evals["Evaluation harness"]
    G[golden_set.csv<br/>37 hand-labelled Qs] --> RUN[evals.run]
    S[generate.py<br/>synthetic Qs via LLM] --> RUN
    RUN --> M[recall@k, MRR, nDCG@10<br/>strict + lenient, per slice, latency]
    M --> J[results/*.json]
  end

  RUN -.calls.-> Q
```

### Components

| Layer | What it does | Key choices |
|---|---|---|
| **API** | FastAPI with JWT bearer auth, role-based access (staff / admin) | bcrypt hashing, identical errors for unknown email and wrong password, 401 vs 403 |
| **Parsing** | Extracts text from PDF, DOCX (including tables), HTML (noise tags stripped), TXT | Rejects empty or scanned files loudly instead of storing nothing |
| **Chunking** | Recursive splitter that prefers paragraph, then sentence, boundaries | Size and overlap come from config, so chunking can be tested as an experiment |
| **Embeddings** | `BAAI/bge-small-en-v1.5`, local, 384 dimensions, normalised | Free and unlimited, which matters because evals re-run many times. Dimension checked against the DB column at startup |
| **Storage** | PostgreSQL + pgvector, HNSW index (`m=16`, `ef_construction=64`) | One database for records and vectors: supersession is a join, hybrid search can use Postgres full-text |
| **Upload** | Document and all its chunks written in one transaction | A failure can never leave a half-ingested document |
| **Search** | Cosine distance, ready documents only, optional re-ranking | Re-ranking is a strategy chosen by config or flag |
| **Re-ranking** | Cross-encoder, LLM pointwise, LLM listwise behind one interface | LLM output is repaired (duplicates, invalid indices, missing items) rather than trusted |
| **LLM access** | Any OpenAI-compatible provider (Groq, Ollama, Cerebras) | Provider is set in `.env`, not in code. Throttled for free-tier limits, `temperature=0` for repeatable evals |

### Repository layout

```
app/
  api/routes/        auth, document_upload, search, health
  api/services/      chunking, embeddings, retrieval, reranker, llm
  api/ingestion/     parser
  core/              config, security
  db/                models, session
evals/
  data/golden_set.csv      hand-labelled questions with evidence quotes
  generate.py              synthetic question generator (LLM, verified)
  metrics.py               is_hit, first_hit_rank, recall@k, MRR, nDCG@k
  run.py                   runs every question through search, saves results
  inspect_rerank.py        side-by-side top chunks, vector vs re-ranked
  check_batch.py           batched vs single cross-encoder scores
  results/                 one JSON per run, with config and per-question ranks
tests/                     55 tests (unit + retrieval against real Postgres)
```

---

## Evaluation method

**Golden set:** 37 hand-written questions against the University of Liverpool student handbook (43 pages, 290 chunks), each with an evidence quote checked by script to exist word for word in the source. Slices: 22 simple, 8 conditional, 7 unanswerable.

**Synthetic set:** `generate.py` splits a document's extracted text into windows, asks an LLM for realistic questions with an exact evidence quote, then rejects any item whose quote doesn't appear in the source or whose wording copies it. It works on extracted text, so it works for any file format.

**Matching:** a retrieved chunk counts as a hit if it contains the evidence quote. Matching on evidence rather than chunk IDs means the same eval set stays valid when chunking changes. Two modes are reported side by side:

- **strict:** exact quote match only
- **lenient:** exact match, or at least 60% of the evidence's words present

**Metrics:** recall@1, @5, @10, MRR, nDCG@10, per slice, plus median and max latency per question. Every run saves its config and every question's rank to `evals/results/`.

---

## Results so far

All runs: one document (UoL handbook), 30 answerable questions, recursive chunking 1000 / 200, `bge-small-en-v1.5`, k = 10.

| Run | strict R@1 | lenient R@1 | strict R@5 | MRR | nDCG@10 | median latency |
|---|---|---|---|---|---|---|
| Vector search (baseline) | 0.60 | 0.80 | 0.967 | 0.876 | 0.871 | 20 ms |
| + bge-reranker-base (20 candidates) | 0.37 | 0.47 | 0.93 | 0.656 | 0.729 | 5,800 ms |
| + bge-reranker-base, RRF-fused with vector rank | 0.67 | 0.80 | 0.90 | 0.878 | 0.871 | 9,400 ms |
| **+ ms-marco-MiniLM-L-6-v2, RRF-fused** | **0.70** | **0.90** | 0.933 | **0.936** | **0.919** | **500 ms** |
| + LLM listwise re-rank, fused (Groq, gpt-oss-120b, 10 candidates) | 0.60 | 0.80 | 0.967 | 0.894 | 0.892 | ~20 s* |
| *Footers stripped, re-chunked (290 → 288 chunks):* | | | | | | |
| Vector search, clean chunks | 0.567 | 0.767 | 0.967 | 0.861 | 0.854 | 100 ms |
| MiniLM, RRF-fused, clean chunks | 0.60 | 0.80 | 0.967 | 0.886 | 0.892 | 500 ms |

\* LLM latency is dominated by a deliberate 20-second gap between calls to stay inside Groq's free-tier token limit. Latency is per question on a laptop CPU, and varied between identical runs (the MiniLM run measured 0.5 s median once and 1.9 s another time), so treat it as a range. The first question of each run also pays the one-off model-load cost, which is why max latency is much higher than the median.

**Current best:** a small English cross-encoder (22M parameters) fused with the vector ranking. The 120B-parameter LLM re-ranker, also fused, barely moved the numbers (MRR 0.876 to 0.894, strict R@1 unchanged) at far higher cost. It lifts MRR from 0.876 to 0.936 and lenient R@1 from 0.80 to 0.90 at about 0.5 s per query, while the larger multilingual re-ranker (278M) on its own made results worse. With 30 questions, differences of one or two questions are within noise, so these are directional results; a larger eval set is needed before treating the gains as settled.

**Reading the baseline:** retrieval nearly always finds the right passage somewhere in the top 5, but puts it first only 60% of the time under strict matching. That gap is what re-ranking was meant to close.

Answerable questions average a top similarity of 0.73 and unanswerable ones 0.66. The gap is small, so a similarity threshold alone won't be enough to decide when to say "I don't know". That feeds into the design of `/ask`.

---

## Findings and trial-and-error log

This is the part of the project I learned the most from, so it's written down in order.

### 1. The re-ranker made search worse, and it wasn't a bug

Adding `bge-reranker-base` dropped strict recall@1 from 0.60 to 0.37 and made each query about 300× slower. Before accepting that, I ruled out the obvious causes:

- **Is the model loaded correctly?** A sanity check scored an obvious match at 0.997 and an obvious non-match at 0.00004. The model works.
- **Is it a batching or padding bug?** `check_batch.py` scores the same 20 candidates all at once and one at a time. The scores were identical to four decimal places.
- **Is the metric just too strict?** `inspect_rerank.py` prints the top chunks side by side. The re-ranker's picks were genuinely wrong, not alternative correct answers.

What it actually did, for *"who do I call in an emergency on campus"*:

| Chunk | Relevant? | Re-ranker score |
|---|---|---|
| "…999 and our Campus support team (2222 from an internal telephone…" | the answer | 0.64 |
| "Serious illness affecting a close family member…" | no | 0.98 |
| "Your Academic Adviser is the first port of **call**…" | no | 0.98 |
| "…'My money? My info? I don't think so'" (fraud advice) | no | 0.98 |

The model latched onto surface cues: the word "call" in "first port of call", and urgent-sounding topics like illness, fraud and security. On long, noisy chunks from a three-column PDF, that beat the actual answer.

**Conclusion:** a re-ranker is not automatically an improvement. It has to be validated on your own corpus, with your own questions, before it goes into the pipeline. Here it would have made the product worse while looking like a best practice.

### 1b. Fusion, and a smaller model, fixed it

Two changes turned the re-ranker from harmful to useful:

- **Reciprocal Rank Fusion.** Instead of letting the re-ranker overrule search, each chunk's final position combines its vector rank and its re-ranker rank. A chunk has to do well in both to come first. With the same bge-reranker-base model, strict R@1 went from 0.37 (re-ranker alone) to 0.67 (fused), slightly above the 0.60 baseline.
- **A smaller, English, search-trained model.** `ms-marco-MiniLM-L-6-v2` is about 12× smaller than bge-reranker-base and trained on real search queries. Fused with vector rank it gave the best result so far (MRR 0.936, nDCG 0.919) at about 0.5 s per query instead of 9 s.

The lesson: bigger isn't automatically better, and a re-ranker should inform the ranking rather than replace it.

### 1c. A retired model name failed silently

The first LLM re-ranking run took about 70 seconds per question instead of 20. Every call was failing: Groq had retired `llama-3.3-70b-versatile` (404, model not found), then the replacement reasoning model (`gpt-oss-120b`) often spent its whole token budget "thinking" and returned an empty answer. Because the listwise re-ranker falls back to the original order on error, the run would have finished normally and reported vector-search results as LLM results.

Fixes: failed calls are now printed as they happen, non-retryable errors (400, 401, 403, 404) stop immediately instead of retrying for a minute, reasoning models get a larger token budget with low reasoning effort, and every run reports `LLM calls / ok / failed` with a warning above 20% failures. The final run had 37 calls, 0 failures.

**Lesson:** a fallback that keeps a pipeline running can also make a broken component look like a working one in evaluation. Failures have to be counted and surfaced, not just survived.

### 1d. The big LLM didn't beat the small cross-encoder

With the model working, the 120B LLM listwise re-ranker (fused) matched the baseline on strict R@1 (0.60) and nudged MRR from 0.876 to 0.894. The 22M MiniLM cross-encoder (fused) did better on every metric (MRR 0.936) and is far cheaper to run. Likely reasons: the LLM only saw the first 600 characters of each of 10 candidates, so answers later in a chunk were cut off, and listwise ranking by a general model is noisier than a model trained specifically for relevance. A task-specific small model beat a general large one here.

### 1e. Removing page footers made the numbers slightly worse, and that is the important result

Stripping the 41 running footers removed about 1% of the text and nothing else. Re-chunking the cleaned text produced 288 chunks instead of 290, and every chunk boundary after the first footer shifted. The scores moved down: baseline MRR 0.876 to 0.861, MiniLM-fused MRR 0.936 to 0.886.

The cleaning itself is almost certainly not harmful. What changed is where each chunk starts and ends, so some evidence sentences landed in a different chunk, next to different neighbours. That boundary shuffle alone moved MRR by 0.05, which is about the same size as the gain the best re-ranker showed.

**Lesson:** with 30 questions and one document, run-to-run differences of 0.03 to 0.05 can come from incidental chunk boundaries, not from the method being tested. The re-ranker gains are real in direction (fused MiniLM beat plain vector search on both chunkings: 0.936 vs 0.876, and 0.886 vs 0.861), but their size isn't settled. The next step is a larger eval set and confidence intervals, not more tuning.

### 2. My own scoring code had two bugs

The first baseline showed recall@1, @5 and @10 all at exactly 0.80. That is almost impossible, because some answers should land at rank 2 or 4. Checking the saved per-question ranks showed every question at rank 1 or not found, nothing in between.

- `return None` was indented inside the loop, so `first_hit_rank` gave up after checking the first result.
- The exact-match check was reversed (`chunk in evidence` instead of `evidence in chunk`), so every hit came from the looser fallback.

After fixing both, R@5 went from 0.80 to 1.00 and MRR from 0.80 to 0.876. The lesson: numbers that look too neat are a reason to check the measuring code, not a reason to celebrate.

### 3. Lenient matching flattered the results

Once both modes were reported, lenient R@1 was 0.80 and strict R@1 was 0.60. Some lenient "hits" were chunks that shared words with the answer without containing it. Some strict "misses" were other chunks that also contained the answer (the emergency number appears in more than one place). The true figure sits between the two, so both are reported and strict is treated as the headline.

### 4. Two "unanswerable" questions were answerable

While building the golden set I planned "what's the wifi password" and "what's the pass mark" as questions the handbook doesn't answer. Checking against the source showed it covers eduroam and states a 40% pass mark for levels 4 to 6. Both were relabelled. If they had stayed wrong, the system would have been penalised for answering correctly. Unanswerable labels have to be checked against the document, not assumed.

### 5. The first chunking choice mixes topics

One chunk contained the end of the Vice-Chancellor's welcome, the emergency number, fire procedures and term dates. A query quoting the emergency sentence word for word ranked that chunk third, because four topics in one chunk give a blurry vector. Character-count chunking cuts across topics. Heading-aware chunking is a planned experiment.

### 6. Synthetic questions need a human check

The generator's automatic checks catch invented quotes and copied wording. They don't catch a question that is too vague to test anything ("where can I find information about services?") or evidence that is technically real but useless (a table-of-contents line). A 10% manual spot-check is part of the process, and its acceptance rate is recorded.

### 7. Test isolation matters

Two search tests passed on an empty database and failed once the real handbook was uploaded, because real chunks outranked the test's hand-made vectors. The tests now hide existing documents inside a rolled-back transaction, so they don't depend on whatever data happens to be there.

### 8. Free LLM tiers change without warning

A provider's free model started returning "402 payment required" partway through the build. Because the LLM is configured in `.env` rather than in code, switching to Groq (or local Ollama) was a three-line change.

---

## Next experiments

1. ~~Score fusion~~ and ~~a smaller re-ranker~~: done, see results.
2. **`BAAI/bge-reranker-v2-m3`:** newer and stronger, to check whether model quality or model size was the issue.
3. ~~LLM listwise re-ranking~~: done. Possible follow-up: full chunk text instead of 600 characters, and 20 candidates, to test whether truncation held it back.
4. ~~Strip page footers~~: done, see finding 1e. **Next:** grow the eval set (synthetic questions plus a second document) and report bootstrap confidence intervals, so small differences can be told apart from noise. Heading-aware chunking after that.
5. **Hybrid search:** keyword plus vector search, for exact terms like clause numbers and phone numbers.
6. **More documents:** a single handbook makes retrieval easier than a real corpus would.

Then: `/ask` with citations and abstention, answer-level metrics (faithfulness, false answer rate), policy versioning, Drive sync, Slack, deployment with the eval harness gating CI.

---

## Running it

```powershell
docker compose up -d                       # Postgres + pgvector
pip install -r requirements.txt
python scripts/create_tables.py
python -m uvicorn app.main:app --reload    # API docs at http://localhost:8000/docs
python -m pytest -q                        # 55 tests
```

Evals:

```powershell
python -m evals.run --name baseline
python -m evals.run --name rerank_cross --rerank-strategy cross
python -m evals.run --name rerank_llm_list --rerank-strategy llm_list
python -m evals.generate --document-id <id> --dry-run
python -m evals.inspect_rerank
```

`.env` settings: `DATABASE_URL`, `JWT_SECRET`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MIN_INTERVAL`, `RERANK_MODEL`, `RERANK_CANDIDATES`.

---

## Limitations

- One document, 30 answerable questions. Results are directional, not statistically robust.
- Strict and lenient matching bracket the true recall; neither is exact.
- Latency is measured on a laptop CPU with no GPU.
- No answer generation yet, so there are no answer-quality or abstention metrics.
- Not deployed.

---

## Stack

Python, FastAPI, SQLAlchemy, PostgreSQL + pgvector, sentence-transformers, LangChain text splitters, pypdf, python-docx, BeautifulSoup, PyJWT, bcrypt, pytest, Docker. LLMs via Groq or Ollama.
