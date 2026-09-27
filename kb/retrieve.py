"""Hybrid retrieval. PHASE 2.

Dense vectors plus BM25, merged by reciprocal rank fusion. Pure vector
search is weak on exactly what this corpus is full of -- equipment tags,
clause numbers, standard references like IS 2062 or API 610. Keyword
search catches those, vectors catch the paraphrases, and the combination
beats either alone on technical corpora.
"""

from __future__ import annotations

from typing import Any

RRF_K = 60


def search(query: str, top_k: int = 5, collection_name: str = "default") -> list[dict[str, Any]]:
    # TODO(phase 2): dense query via inference.client.embed, BM25 over the
    # same chunk set, then reciprocal rank fusion:
    #     score(d) = sum over rankings of 1 / (RRF_K + rank(d))
    return []
