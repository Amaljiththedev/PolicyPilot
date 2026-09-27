"""Re-ranking strategies.

    cross        cross-encoder scores decide the order
    llm_point    LLM scores each chunk 0-10, one call per chunk
    llm_list     LLM orders all chunks in one call
    *_fused      any of the above, combined with the original vector ranking
                 by Reciprocal Rank Fusion (RRF): a chunk has to rank well in
                 BOTH lists to come first, so one bad re-ranker can't overrule search.
"""
from functools import lru_cache

from sentence_transformers import CrossEncoder

from app.api.services.llm import chat_json
from app.core.config import get_settings

settings = get_settings()
MAX_CHARS = 600   # trim each chunk in LLM prompts to keep them short
RRF_K = 60        # standard RRF constant; dampens the gap between rank 1 and rank 2


# ---------- 1. cross-encoder ----------
@lru_cache
def get_cross_encoder(model_name: str) -> CrossEncoder:
    return CrossEncoder(model_name)


def _cross(query: str, hits: list[dict]) -> list[float]:
    model = get_cross_encoder(settings.RERANK_MODEL)
    return [float(s) for s in model.predict([(query, h["text"]) for h in hits])]


# ---------- 2. LLM pointwise: score each chunk on its own ----------
POINT_PROMPT = """Rate how well the PASSAGE answers the QUESTION.
0 = irrelevant, 5 = related but does not answer, 10 = directly answers it.
Judge only what the passage says. Return JSON: {{"score": <integer 0-10>}}

QUESTION: {q}
PASSAGE: {p}"""


def _llm_point(query: str, hits: list[dict]) -> list[float]:
    scores = []
    for h in hits:
        try:
            s = chat_json(POINT_PROMPT.format(q=query, p=h["text"][:MAX_CHARS]), max_tokens=50)
            scores.append(float(s.get("score", 0)))
        except Exception:
            scores.append(-1.0)   # failed call: rank it last, don't crash the run
    return scores


# ---------- 3. LLM listwise: order all chunks in one call ----------
LIST_PROMPT = """Below are {n} passages, numbered [1] to [{n}].
Rank them by how well they answer the QUESTION, most relevant first.
Include every number exactly once.
Return JSON: {{"ranking": [<numbers in order>]}}

QUESTION: {q}

{passages}"""


def _llm_list(query: str, hits: list[dict]) -> list[float]:
    passages = "\n\n".join(f"[{i + 1}] {h['text'][:MAX_CHARS]}" for i, h in enumerate(hits))
    try:
        out = chat_json(LIST_PROMPT.format(n=len(hits), q=query, passages=passages), max_tokens=300)
        order = [int(x) - 1 for x in out.get("ranking", [])]
    except Exception:
        order = []
    # keep only valid, unique positions; append anything the LLM forgot, in original order
    seen, clean = set(), []
    for i in order + list(range(len(hits))):
        if 0 <= i < len(hits) and i not in seen:
            seen.add(i)
            clean.append(i)
    # convert the order into scores: first place gets the highest score
    scores = [0.0] * len(hits)
    for rank, i in enumerate(clean):
        scores[i] = float(len(hits) - rank)
    return scores


BASE = {"cross": _cross, "llm_point": _llm_point, "llm_list": _llm_list}
STRATEGIES = list(BASE) + [f"{s}_fused" for s in BASE]


# ---------- fusion ----------
def rrf_fuse(rerank_scores: list[float]) -> list[float]:
    """Reciprocal Rank Fusion of the vector order (input order) and the re-ranker order.

    RRF score = 1/(k + vector_rank) + 1/(k + rerank_rank). Uses ranks, not raw scores,
    so it doesn't matter that cosine and cross-encoder scores are on different scales.
    """
    n = len(rerank_scores)
    vector_rank = list(range(1, n + 1))                       # hits arrive sorted by vector score
    order = sorted(range(n), key=lambda i: rerank_scores[i], reverse=True)
    rerank_rank = [0] * n
    for r, i in enumerate(order, 1):
        rerank_rank[i] = r
    return [1 / (RRF_K + vector_rank[i]) + 1 / (RRF_K + rerank_rank[i]) for i in range(n)]


def rerank(query: str, hits: list[dict], top_k: int, strategy: str | None = None) -> list[dict]:
    if not hits:
        return []
    strategy = strategy or settings.RERANK_STRATEGY
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown rerank strategy: {strategy} (choose from {STRATEGIES})")

    fused = strategy.endswith("_fused")
    scores = BASE[strategy.removesuffix("_fused")](query, hits)
    if fused:
        for h, s in zip(hits, scores):
            h["rerank_score"] = round(s, 4)
        scores = rrf_fuse(scores)

    for h, s in zip(hits, scores):
        h["vector_score"] = h["score"]
        h["score"] = round(s, 6)
    # sort by new score; ties broken by original vector score
    hits.sort(key=lambda h: (h["score"], h["vector_score"]), reverse=True)
    return hits[:top_k]
