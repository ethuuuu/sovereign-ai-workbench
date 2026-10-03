"""Measure whether free threading is worth it ON THIS MACHINE.

    python3.14  scripts/bench_parallel.py    # standard build, GIL
    python3.14t scripts/bench_parallel.py    # free-threaded

Run both and compare. The claim in the README is a measurement, not a
belief, and this is the thing that made it.
"""

from __future__ import annotations

import hashlib
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.parallel import gil_state  # noqa: E402
from kb import chunking  # noqa: E402

VOCAB = [
    "pump", "valve", "flange", "gasket", "inspection", "tolerance", "pressure",
    "vibration", "calibration", "shutdown", "permit", "isolation", "API 610",
    "IS 2062", "clearance", "bearing", "alignment", "thickness", "corrosion",
]


def sample_sop(index: int, clauses: int = 140) -> str:
    random.seed(index)
    lines = [f"STANDARD OPERATING PROCEDURE SOP-{index:04d}", ""]
    for clause in range(1, clauses + 1):
        body = " ".join(random.choice(VOCAB) for _ in range(60))
        lines.append(f"{clause}.{clause % 5 + 1} {body}")
    return "\n".join(lines)


def work(text: str) -> int:
    page = chunking.Page(1, text)
    chunks = chunking._chunk_page(Path("bench.txt"), page)
    for chunk in chunks:
        hashlib.sha1(chunk.text.encode()).hexdigest()
    return len(chunks)


def timed(docs: list[str], workers: int) -> float:
    start = time.perf_counter()
    if workers == 1:
        for doc in docs:
            work(doc)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, docs))
    return time.perf_counter() - start


def main() -> int:
    state = gil_state()
    print(state.describe())
    print()

    docs = [sample_sop(i) for i in range(96)]
    timed(docs[:8], 1)  # warm

    baseline = None
    ladder = [w for w in (1, 2, 4, 8, 16) if w <= max(2, state.cpu_count * 2)]
    for workers in ladder:
        best = min(timed(docs, workers) for _ in range(3))
        if baseline is None:
            baseline = best
        print(f"  {workers:>2} thread(s)  {best:6.3f}s   {baseline / best:4.2f}x")

    print()
    if state.scales:
        print("Free threading is active. Run kb.ingest on this interpreter.")
    elif state.free_threaded_build:
        print("Free-threaded build, but the GIL came back on. Something in "
              "this process imported a C extension that is not declared "
              "safe. Find it before trusting these numbers.")
    else:
        print("Standard build. Threads will not help CPU-bound Python here, "
              "which is why kb.ingest runs serially unless free-threaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
