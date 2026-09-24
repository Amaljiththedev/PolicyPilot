# PolicyPilot — Theory Notes, Phases 1–4

What you've built, why each piece exists, and how to explain it. Each section ends with the interview answer and a few self-check questions. If you can answer the self-checks without looking, you understand that phase.

---

## The whole system in one picture

```
WRITE PATH (once per document)
upload → parse → chunk → embed → store in Postgres/pgvector

READ PATH (once per question)
question → embed → search (HNSW) → re-rank → LLM with chunks → answer + citations
                    ↑_____ agent can loop and search again, or escalate _____|
```

The two paths only meet in the database. Ingestion can finish weeks before anyone asks a question. That separation is why you can re-chunk or re-embed the whole corpus without touching query code.

**You have built:** everything up to and including `embed`. Next is the upload route that stores it, then the read path.

---

## Phase 1 — Scaffold and configuration

### What it is
Project layout, dependencies, Docker, and one central settings object.

### Key ideas

**Layered structure.** `core/` (config, security), `db/` (models, session), `schemas/` (API shapes), `api/` (routes), `services/` (business logic), `ingestion/` (parsing). Services don't know about HTTP; routes don't contain business logic. That's why your eval harness can later call `chunk_text()` directly with no web server involved.

**12-factor config.** Settings come from environment variables (`.env`), not hardcoded values. Same code runs locally, in CI and in AWS — only the environment changes. Secrets never go in the repo.

**Docker / docker-compose.** The container is the unit you ship. `docker compose up` brings up Postgres-with-pgvector and the API together, so "works on my machine" means "works everywhere."

**Pinned dependencies.** Exact versions in `requirements.txt`. You already hit why: bcrypt 4.1 broke passlib 1.7.4.

### Interview answer
"I separated the app into layers so business logic has no dependency on HTTP — that's what lets my evaluation harness call the chunker and retriever directly. Config is environment-driven so the same image runs locally and in the cloud, and the whole stack comes up with one docker-compose command."

### Self-check
- Why does it matter that `services/` doesn't import FastAPI?
- What goes in `.env` vs `.env.example`, and why is only one committed?
- What broke when bcrypt wasn't pinned?

---

## Phase 2 — Database layer

### What it is
Five tables (users, documents, chunks, queries, feedback), defined with SQLAlchemy, in Postgres with the pgvector extension.

### Key ideas

**ORM (Object-Relational Mapper).** SQLAlchemy maps Python classes to tables. You write `User(email=...)` instead of raw SQL. `Mapped[...]` and `mapped_column` are the SQLAlchemy 2.0 typed style.

**Declarative Base.** `class Base(DeclarativeBase)` — every model inherits from it, and `Base.metadata.create_all()` builds every table it knows about.

**Session.** A unit of work with the database. `get_db()` opens one per request and always closes it (the `try/finally` with `yield`).

**Primary keys and foreign keys.** `chunks.document_id → documents.id`. `ondelete="CASCADE"` means deleting a document deletes its chunks — no orphans.

**Relationships.** `Document.chunks` / `Chunk.document` let you navigate between objects in Python. `cascade="all, delete-orphan"` does the cascade at the ORM level too.

**Indexes.** A B-tree index on a column makes lookups by that column fast. Primary keys are already indexed — which is why `index=True` on `id` created a pointless duplicate.

**pgvector.** A Postgres extension adding a `vector(n)` column type and distance operators:
- `<=>` cosine distance
- `<->` Euclidean (L2) distance
- `<#>` negative inner product

**Vector dimension is part of the schema.** `vector(384)` only accepts 384 numbers. Change embedding models and you must recreate the column. That's the 1536-vs-384 problem.

**HNSW index.** Hierarchical Navigable Small World — a layered graph where each vector links to its near neighbours. Search enters at the sparse top layer and descends, getting closer at each step. Result: near-instant search at scale.
- It's **ANN (approximate nearest neighbour)** — it can occasionally miss the true nearest match in exchange for speed.
- `m=16` — links per node (more = better recall, more memory).
- `ef_construction=64` — how thoroughly the graph is built (more = better graph, slower build).
- `vector_cosine_ops` — tells the index which distance you'll query with. Must match the operator you use.
- Alternative: **IVFFlat** — clusters vectors and searches only nearby clusters. Faster to build, needs training data, usually lower recall than HNSW.

**Why Postgres + pgvector instead of Chroma/Pinecone.** One database for relational data and vectors: joins, transactions, one backup. Your supersession filter is a join, and hybrid search needs Postgres full-text search. Two databases would mean syncing them by hand.

### Interview answer
"Five tables in Postgres with pgvector. Chunks store their embedding in a `vector(384)` column with an HNSW index using cosine ops, so similarity search stays fast as the corpus grows. I chose pgvector over a dedicated vector store because I needed relational data anyway — my supersession filter is a join and hybrid search uses Postgres full-text — so one database beat keeping two in sync."

### Self-check
- What does `ondelete="CASCADE"` prevent?
- Why did changing embedding models mean recreating the table?
- HNSW is "approximate" — what's traded for what?
- What would happen if the index used `vector_cosine_ops` but you queried with `<->`?

---

## Phase 3 — Authentication

### What it is
Users register and log in; every protected route requires a valid JWT.

### Key ideas

**AuthN vs AuthZ.** Authentication = *who are you* (401 if it fails). Authorisation = *are you allowed* (403 if it fails). `get_current_user` is authN; `require_admin` is authZ.

**Password hashing, not encryption.** Hashing is one-way. You never store the password, only `bcrypt(password + salt)`.
- **Salt** — random per user, stored inside the hash string. Same password → different hashes. Defeats rainbow tables.
- **Work factor** — bcrypt is deliberately slow, so brute-forcing a stolen database is expensive.
- **bcrypt 72-byte limit** — longer passwords are silently truncated. That's why `max_length=72` on `UserCreate`.
- OWASP's current first choice is Argon2id; bcrypt is the pragmatic, defensible choice.

**Constant-time comparison.** `verify_password` uses the library, never `==`. A plain comparison returns faster on an early mismatch, and that timing leaks information.

**JWT (JSON Web Token).** `header.payload.signature`, each Base64URL-encoded.
- Payload holds `sub` (user id) and `exp` (expiry).
- Signature = HMAC-SHA256(header + payload, secret). Proves the token wasn't altered.
- **Base64 is not encryption** — anyone can read the payload. Never put secrets in it.
- Pin the algorithm on decode (`algorithms=["HS256"]`) — never trust the token's own header.
- **Stateless:** the server verifies the signature, no database lookup. The trade-off: you can't revoke a token before it expires. Short expiry (30 min) limits the damage.

**JWT claims come back as strings.** `create_access_token(42)` decodes to `"42"`. Cast before querying.

**User enumeration.** Login returns the same error for "no such email" and "wrong password", and runs a dummy hash check when the user doesn't exist — so neither the message nor the *response time* reveals which emails are registered.

**Separate schemas for in and out.** `UserCreate` (accepts password), `UserRead` (never has a password field). `response_model=UserRead` means the hash *cannot* leak through the API, even by accident.

**HTTPBearer(auto_error=False).** Lets your code handle the missing-header case, so you can return the exact error message your tests expect.

### Interview answer
"Passwords are bcrypt-hashed with a per-user salt, verified in constant time. Login returns a short-lived HS256 JWT with the user id and expiry; the algorithm is pinned on decode. A FastAPI dependency validates the token on every protected route and returns 401, with a separate admin dependency returning 403. Login gives identical errors and timing for unknown emails and wrong passwords to prevent user enumeration. The trade-off with JWTs is revocation — I use short expiry, and in production I'd add a denylist."

### Self-check
- 401 vs 403 — give an example of each in your app.
- Why can anyone read a JWT's payload, and why does that not break security?
- What's the timing attack in login, and how does the dummy hash fix it?
- Why does `UserRead` exist separately from `UserCreate`?

---

## Phase 4 — Ingestion (the write path)

### 4a. Parsing

**Job:** bytes in, clean text out.

- **Dispatch table** (`PARSERS` dict) — each format is one function plus one entry. Adding a format doesn't touch existing code.
- **PDF (pypdf):** wrap bytes in `BytesIO`; `extract_text()` can return `None`, so `or ""`.
- **DOCX:** tables live outside `doc.paragraphs` — read `doc.tables` too or you lose the numbers.
- **HTML:** strip `script`, `style`, `nav`, `header`, `footer` first or chunks fill with menu text.
- **Normalisation:** collapse whitespace but **keep paragraph breaks** (`\n\n`) — the chunker uses them.
- **Empty-document guard:** a scanned PDF parses without error and returns nothing. Fail loudly at upload rather than store a document with zero chunks.
- **Why not CSV:** tabular data has no prose; character-window chunking cuts rows mid-way and loses headers. Different retrieval problem.

### 4b. Chunking

**Why chunk at all:** embedding models have a token limit (bge-small: 512), and one vector for a whole document averages every topic into mush with nothing specific to cite. The chunk is the unit of retrieval, so it's the unit of embedding.

**Strategies:**

| Strategy | How | Trade-off |
|---|---|---|
| Fixed-size | Cut every N chars | Crude, cuts mid-sentence. Your baseline. |
| Recursive | Try `\n\n`, then `\n`, then `. `, then ` ` | Breaks at the most natural boundary available. Your default. |
| Sentence | Group N sentences | Never cuts a sentence; uneven sizes. |
| Structure-aware | Split on headings / numbered clauses | Best for policy & legal text. Your M3 third arm. |
| Semantic | Break where adjacent-sentence similarity drops | Costly (embed every sentence), mixed evidence. |
| Contextual | Prepend an LLM summary to each chunk before embedding | Strong results; costs an LLM call per chunk. |

**Overlap:** neighbouring chunks share a tail, so an idea straddling a boundary appears whole somewhere. Must be less than chunk size or the window never advances.

**The duplicate-tail bug you fixed:** a final fixed window no longer than the overlap is entirely inside the previous chunk — a wasted, duplicate vector.

**Chunk size trade-off:** too small → fragments with no context; too large → blurry vectors, less precise citations. It's a tunable, and tuning it is an experiment for the eval harness, not a guess.

**LangChain vs your own:** you used `RecursiveCharacterTextSplitter` behind your own `chunk_text()` interface, so strategies stay swappable by config.

### 4c. Embeddings

**What:** a model maps text to a fixed-length vector (384 numbers for bge-small) so that similar meanings land close together. "Similar meaning" becomes "small distance," which is computable.

**Cosine similarity:** the angle between vectors. 1 = same direction, 0 = unrelated. You normalise vectors to length 1, which makes cosine and dot product identical.

**Semantic vs lexical:** embeddings match meaning ("holiday" ↔ "annual leave"); keyword search (BM25) matches exact words. Embeddings are weak at exact terms like clause numbers → **hybrid search** combines both.

**Bi-encoder vs cross-encoder:**
- Bi-encoder (your embedding model): query and document embedded separately. Fast — documents pre-computed. Less precise.
- Cross-encoder (your future re-ranker): reads query and document together. Much more precise, too slow for the whole corpus.
- Pattern: **retrieve with bi-encoder (top ~25), re-rank with cross-encoder (top ~5).**

**Asymmetric embeddings:** BGE expects a prefix on queries, not passages. That's `embed_query` vs `embed_texts`.

**Your engineering choices:**
- **Local model** (sentence-transformers) — no cost, no rate limit, reproducible. Matters because the eval harness re-embeds repeatedly.
- **`lru_cache` on `get_model`** — load once per process, not per request.
- **Batching** — embed the whole list in one `encode` call.
- **Dimension check at load** — mismatch fails at startup with instructions, not as a Postgres error mid-ingest.
- **`warm_up()` at app start** — first request isn't slow, and bad config fails early.

**Types to know by name:** dense (yours), sparse (SPLADE), multi-vector / late interaction (ColBERT), Matryoshka (truncatable dimensions), multimodal (CLIP). **MTEB** = the standard embedding benchmark.

**What goes wrong:** embedding documents and queries with different models; dimension mismatch; domain gap (general model doesn't know "covenant"); chunks without context.

### Interview answer (the whole write path)
"On upload I extract text with a per-format parser, then split it with a recursive splitter that prefers paragraph, then sentence boundaries, with overlap so ideas at edges aren't lost. Each chunk is embedded locally with bge-small into a 384-dimensional normalised vector and stored in Postgres with an HNSW index. I run embeddings locally because my evaluation harness re-embeds the corpus for every chunking experiment, so an API would mean cost and rate limits. The embedding service checks the model's dimension against the database column at startup, so a config mistake fails immediately rather than mid-ingestion."

### Self-check
- Why is the chunk the unit of embedding rather than the document?
- Why keep `\n\n` in the parser output?
- Explain bi-encoder vs cross-encoder in two sentences.
- Why does BGE want a prefix on queries but not documents?
- "Holiday" matches "annual leave" — what does that prove, and what kind of query would embeddings get wrong?

### 4d. The upload endpoint — `POST /documents`

**Job:** tie the pipeline together behind one HTTP call: file in, document + chunks + vectors stored.

```
auth (get_current_user) → validate file (type, size) → read bytes
→ extract_text → chunk_text → embed_texts
→ one transaction: insert Document, insert N Chunks → commit
→ 201 + DocumentRead (id, filename, chunk_count)
```

- **`UploadFile` + multipart/form-data.** Files aren't sent as JSON; they arrive as multipart form parts. FastAPI gives you `.filename`, `.content_type`, `await file.read()`.
- **Validate before expensive work.** Check type and max size first. Unsupported → 415, too large → 413, empty/scanned PDF → 422, no token → 401.
- **Map domain errors to HTTP codes.** Parser raises `UnsupportedFileType` / `EmptyDocument` / `CorruptDocument`; the route translates. Services stay HTTP-free.
- **Atomicity.** Document and all its chunks commit together; any failure → `rollback()`. Never a half-ingested document. (The "A" in ACID.)
- **Bulk insert.** `db.add_all(chunks)` + one commit, not a commit per chunk.
- **`chunk_index`.** Keeps order — needed for neighbouring context and citations.
- **Ownership.** `uploaded_by = current_user.id` for access control and audit.
- **Sync vs background.** Right now the user waits during ingestion. At scale: return `202 Accepted`, `status="processing"`, run the pipeline in a worker (BackgroundTasks, Celery, SQS). Classic follow-up question.
- **Duplicates.** Store a SHA-256 of the file to detect re-uploads instead of doubling chunks in search.
- **Blocking CPU work.** Embedding inside an `async def` route blocks the event loop for every user. Use a plain `def` route (runs in a threadpool) or `run_in_threadpool`.

**Testing:** `app.dependency_overrides` for `get_current_user` and `get_db`, mock `embed_texts`, then assert 201 + chunk count on a good .txt, 415 on `.exe`, 422 on empty, 401 without a token.

### Interview answer (endpoint)
"The upload route validates type and size first, then runs parse, chunk and embed, and writes the document and all its chunks in one transaction so a failure can never leave a half-ingested document. Parser exceptions map to 415 and 422 at the route, keeping ingestion independent of HTTP. It's synchronous for now; at scale I'd return 202 and move the pipeline to a background worker with a status field on the document."

### Self-check
- Why is the whole upload one transaction?
- Status code for: wrong type, empty scanned PDF, no token, file too big?
- Why can an `async def` route that embeds slow down every other user?
- When would you switch to 202 + background processing?

---

## Buzzword sheet

| Term | One line |
|---|---|
| RAG | Retrieve relevant text, then generate an answer grounded in it |
| Agentic RAG | The model calls retrieval as a tool, can search again or refuse |
| Embedding | Text → vector where distance ≈ meaning difference |
| Vector store | Database for embeddings (pgvector, Pinecone, Qdrant, Chroma) |
| ANN | Approximate nearest neighbour — fast, near-exact search |
| HNSW | Graph-based ANN index; what you use |
| IVFFlat | Cluster-based ANN index; alternative |
| Top-k | How many chunks you retrieve |
| Hybrid search | Keyword + vector, fused (e.g. Reciprocal Rank Fusion) |
| Re-ranker | Cross-encoder that re-scores retrieved candidates |
| Chunk overlap | Shared text between neighbouring chunks |
| JWT | Signed, stateless token: header.payload.signature |
| Salt | Random per-user value mixed into a password hash |
| Recall@k | Did the right chunk appear in the top k? (Phase M2) |
| Faithfulness | Is every claim in the answer supported by retrieved text? (M2) |
| OKF | Google's markdown+YAML knowledge-base format — a storage format, not a retrieval method |

---

## Where this is going

- **Done:** `POST /documents` — Phase 4 closed.
- **Now — Phase 5:** retrieval — embed the question, nearest chunks by cosine distance.
- **M2:** evaluation harness *before* any improvements, so every later change has a before-and-after number.
- **Then:** re-ranker, hybrid search, chunking comparison, supersession, agent loop.

**Keep collecting the golden set:** every time you test a question by hand, write the question and the chunk that should answer it into `evals/data/golden_set.csv`.
