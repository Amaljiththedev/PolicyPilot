"""Chunk-size ablation: re-chunk, run the eval, repeat. Restores 1000/200 cleaned at the end.

    python scripts/chunk_sweep.py --document-id 31
    python scripts/chunk_sweep.py --document-id 31 --sizes 500 1000 1500 --search-mode hybrid
"""
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals import run
from scripts.rechunk import main as rechunk


def main(doc_id, sizes, search_mode, rerank_strategy):
    try:
        for size in sizes:
            overlap = size // 5                      # keep overlap at 20%
            print(f"\n===== chunk size {size}, overlap {overlap} =====")
            rechunk(doc_id, clean=True, size=size, overlap=overlap)
            tag = f"chunk{size}_{search_mode or 'vector'}" + (f"_{rerank_strategy}" if rerank_strategy else "")
            run.get_settings().CHUNK_SIZE, run.get_settings().CHUNK_OVERLAP = size, overlap
            run.main(tag, rerank_strategy=rerank_strategy, search_mode=search_mode)
    finally:
        print("\nrestoring 1000/200 cleaned chunks")
        rechunk(doc_id, clean=True, size=1000, overlap=200)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--document-id", type=int, required=True)
    p.add_argument("--sizes", type=int, nargs="+", default=[500, 1000, 1500])
    p.add_argument("--search-mode", choices=("vector", "keyword", "hybrid"), default=None)
    p.add_argument("--rerank-strategy", default=None)
    a = p.parse_args()
    main(a.document_id, a.sizes, a.search_mode, a.rerank_strategy)
