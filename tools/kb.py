"""Local knowledge base search.

PHASE 2 -- the interface is final, the index is not yet built. kb_search
returns a clear "not indexed yet" message until kb/ingest.py has run, so
the agent degrades to answering without citations rather than crashing.

Design (see kb/ for the implementation):
  - clause-aware chunking: split on headings and clause numbers first,
    fall back to 800-token windows with 100-token overlap
  - hybrid retrieval: dense vectors plus BM25, merged by reciprocal rank
    fusion. Pure vector search is weak on exactly what this corpus is full
    of -- equipment tags, clause numbers, standards like IS 2062 or API 610
  - every chunk carries source path, page and section, so a claim can cite
"""

from __future__ import annotations

from config import resolve_path
from guard import audit
from tools.base import REGISTRY, prop


def is_indexed() -> bool:
    root = resolve_path("knowledge_base")
    return root.is_dir() and any(root.glob("*/chunks.jsonl"))


@REGISTRY.register(
    "kb_search",
    "Search the organisation's manuals, SOPs and past correspondence. "
    "Returns passages with their source file and page. Any factual claim "
    "you draw from these must cite the passage id.",
    {
        "query": prop("What to look for"),
        "top_k": prop("How many passages to return", "integer"),
    },
    ["query"],
)
def kb_search(args: dict) -> str:
    query = args["query"]
    top_k = int(args.get("top_k", 5))

    if not is_indexed():
        audit.write("kb_search_unindexed", {"query": query})
        return (
            "The knowledge base has not been indexed yet. Run:\n"
            "  python3.14t -m kb.ingest --source /path/to/manuals "
            "--collection sop\n"
            "Answer from the documents in this conversation instead, and say "
            "plainly that no organisational source was available."
        )

    from kb.retrieve import collections, search

    names = collections()
    hits: list = []
    for name in names:
        hits.extend(search(query, top_k=top_k, collection_name=name))
    hits = sorted(hits, key=lambda h: -h["score"])[:top_k]
    audit.write("kb_search", {"query": query, "hits": len(hits)})
    if not hits:
        return "No matching passages."

    return "\n\n".join(
        f"[{h['id']}] {h['source']} p.{h['page']}"
        + (f" - {h['section']}" if h.get("section") else "")
        + f" (score {h['score']:.2f})\n{h['text']}"
        for h in hits
    )
