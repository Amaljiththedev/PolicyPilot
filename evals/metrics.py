import math
import re 
from statistics import mean



_WORD = re.compile(r"[a-z0-9£$%]+")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())



def is_hit(chunk_text: str, evidence: str, min_coverage: float = 0.6) -> bool:
    
    if _norm(evidence) in _norm(chunk_text):  
        return True
    ev=_tokens(evidence)

    if not ev:
        return False

    chunk_words = set( _tokens(chunk_text))

    return sum(w in chunk_words for w in ev) / len(ev) >= min_coverage

def first_hit_rank(chunk_texts: list[str], evidence: str) -> int | None:

    for rank,text in enumerate(chunk_texts,start=1):
        if is_hit(text,evidence):
            return rank
    return None

def recall_at_k(ranks: list[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)



def mrr(ranks: list[int | None]) -> float:
    """Mean reciprocal rank: rank 1 -> 1.0, rank 2 -> 0.5, rank 3 -> 0.33, missed -> 0."""
    if not ranks:
        return 0.0
    return mean(1.0 / r if r else 0.0 for r in ranks)


def ndcg_at_k(chunk_texts: list[str], evidence: str, k: int = 10) -> float:
    """Normalised Discounted Cumulative Gain with binary relevance.

    Every retrieved chunk that contains the evidence counts as relevant (1),
    others 0. A relevant chunk at rank r is worth 1 / log2(r + 1), so rank 1 = 1.0,
    rank 2 = 0.63, rank 3 = 0.5 ... (DCG). Divide by the best possible DCG (all
    relevant chunks at the top) to get a score between 0 and 1.

    Unlike MRR, it rewards EVERY relevant chunk near the top, not just the first.
    Limitation: "ideal" uses the relevant chunks found in the top k, because we
    don't label every relevant chunk in the whole corpus.
    """
    rels = [1 if is_hit(t, evidence) else 0 for t in chunk_texts[:k]]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
    ideal = sorted(rels, reverse=True)
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0
