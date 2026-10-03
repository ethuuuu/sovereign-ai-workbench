"""Index a folder of manuals, SOPs and correspondence.

    python3.14t -m kb.ingest --source /data/sop --collection sop

Run this with the FREE-THREADED interpreter when you have it. Extraction
and chunking are pure-Python and CPU-bound, which is the one shape in this
project that scales across cores once the GIL is gone. Measured on the
project's own chunking workload (scripts/bench_parallel.py), 2 cores:
standard build 0.77x with threads (slower), free-threaded 1.74x.

This module deliberately never imports python-docx: it drags in lxml,
which has not declared itself free-thread safe, and loading it switches
the GIL back on for the whole process. .docx is unzipped with the stdlib
in kb/chunking.py instead.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from agent import parallel
from config import resolve_path
from kb import chunking


def discover(source: Path) -> list[Path]:
    return sorted(
        p
        for p in source.rglob("*")
        if p.is_file() and p.suffix.lower() in chunking.SUPPORTED
    )


def ingest(source: Path, collection: str, workers: int | None = None) -> dict:
    files = discover(source)
    if not files:
        return {"files": 0, "chunks": 0, "notes": ["no supported files found"]}

    state = parallel.gil_state()
    used = parallel.cpu_workers(workers)
    print(f"  interpreter: {state.describe()}")
    print(f"  {len(files)} file(s), {used} worker thread(s)")

    started = time.perf_counter()
    results = parallel.map_cpu(chunking.process, files, workers)
    elapsed = time.perf_counter() - started

    chunks, notes = [], []
    for file_chunks, note in results:
        chunks.extend(file_chunks)
        if note:
            notes.append(note)

    out_dir = resolve_path("knowledge_base") / collection
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "chunks.jsonl"
    with index_path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.as_dict(), ensure_ascii=False) + "\n")

    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "collection": collection,
                "source": str(source),
                "files": len(files),
                "chunks": len(chunks),
                "seconds": round(elapsed, 3),
                "workers": used,
                "free_threaded": state.scales,
                "interpreter": state.version,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "files": len(files),
        "chunks": len(chunks),
        "seconds": round(elapsed, 3),
        "workers": used,
        "index": str(index_path),
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a document folder.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--collection", default="default")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override worker threads. Default: one under the GIL, one per "
             "core when free-threaded.",
    )
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"No such folder: {args.source}", file=sys.stderr)
        return 1

    print(f"Ingesting {args.source} -> collection '{args.collection}'")
    result = ingest(args.source, args.collection, args.workers)

    print(
        f"  {result['chunks']} chunks from {result['files']} files "
        f"in {result.get('seconds', 0)}s"
    )
    for note in result.get("notes", []):
        print(f"  note: {note}")
    if result["chunks"]:
        print(f"  index: {result['index']}")
        print("  BM25 retrieval is live. Dense vectors are still TODO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
