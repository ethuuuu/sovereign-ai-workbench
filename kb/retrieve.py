"""Retrieval over the ingested chunks.

BM25 is implemented here in plain Python rather than pulled from a
package: it is forty lines, it adds no dependency to an air-gapped
install, and it has no C extension that could switch the GIL back on.

Dense vectors are still TODO. When they land, the two rankings merge by
reciprocal rank fusion -- pure vector search is weak on exactly what this
corpus is full of (equipment tags, clause numbers, references like
IS 2062 or API 610), and keyword search is weak on paraphrase.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent import parallel
from config import resolve_path

K1 = 1.5
B = 0.75
RRF_K = 60
_WORD = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@dataclass
class Index:
    chunks: list[dict[str, Any]]
    tokenised: list[list[str]]
    doc_freq: Counter
    avg_len: float

    def __len__(self) -> int:
        return len(self.chunks)


@lru_cache(maxsize=4)
def load(collection: str = "default") -> Index | None:
    path = resolve_path("knowledge_base") / collection / "chunks.jsonl"
    if not path.is_file():
        return None

    chunks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    if not chunks:
        return None

    # Tokenising the whole corpus is CPU-bound pure Python, so it is one of
    # the places free threading pays for itself on a cold start.
    tokenised = parallel.map_cpu(lambda c: tokenize(c["text"]), chunks)

    doc_freq: Counter = Counter()
    for terms in tokenised:
        doc_freq.update(set(terms))
    avg_len = sum(len(t) for t in tokenised) / len(tokenised)
    return Index(chunks, tokenised, doc_freq, avg_len)


def collections() -> list[str]:
    root = resolve_path("knowledge_base")
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "chunks.jsonl").is_file())


def search(
    query: str, top_k: int = 5, collection_name: str = "default"
) -> list[dict[str, Any]]:
    index = load(collection_name)
    if index is None:
        return []

    terms = tokenize(query)
    if not terms:
        return []

    total = len(index)
    idf = {
        term: math.log(1 + (total - index.doc_freq[term] + 0.5)
                       / (index.doc_freq[term] + 0.5))
        for term in set(terms)
        if index.doc_freq.get(term)
    }
    if not idf:
        return []

    def score(position: int) -> tuple[int, float]:
        doc = index.tokenised[position]
        length = len(doc) or 1
        counts = Counter(doc)
        total_score = 0.0
        for term, weight in idf.items():
            freq = counts.get(term, 0)
            if not freq:
                continue
            total_score += weight * (freq * (K1 + 1)) / (
                freq + K1 * (1 - B + B * length / index.avg_len)
            )
        return position, total_score

    scored = parallel.map_cpu(score, range(total))
    ranked = sorted((s for s in scored if s[1] > 0), key=lambda x: -x[1])[:top_k]

    return [
        {
            "id": index.chunks[position]["id"],
            "text": index.chunks[position]["text"][:1200],
            "source": Path(index.chunks[position]["source"]).name,
            "page": index.chunks[position]["page"],
            "section": index.chunks[position].get("section", ""),
            "score": value,
        }
        for position, value in ranked
    ]
