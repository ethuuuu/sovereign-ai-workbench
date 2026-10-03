"""The parallelism decisions, pinned down.

These pass on a standard interpreter too -- that is the point. Nothing in
the project may REQUIRE free threading; it only exploits it when present.
"""

from __future__ import annotations

from pathlib import Path

from agent import parallel
from agent.loop import READ_ONLY_TOOLS
from kb import chunking


def test_gil_state_is_coherent() -> None:
    state = parallel.gil_state()
    if not state.free_threaded_build:
        assert state.gil_currently_enabled
        assert not state.scales
    assert state.describe()


def test_cpu_workers_is_one_under_the_gil() -> None:
    state = parallel.gil_state()
    workers = parallel.cpu_workers()
    if state.scales:
        assert workers > 1 or state.cpu_count == 1
    else:
        assert workers == 1, "threads make CPU-bound work slower under the GIL"


def test_map_cpu_matches_serial_results() -> None:
    items = list(range(50))
    assert parallel.map_cpu(lambda n: n * n, items) == [n * n for n in items]


def test_map_io_preserves_order() -> None:
    items = ["a", "b", "c", "d"]
    assert parallel.map_io(str.upper, items) == ["A", "B", "C", "D"]


def test_only_side_effect_free_tools_run_concurrently() -> None:
    for unsafe in ("write_file", "run_python", "run_tests", "make_docx",
                   "make_xlsx", "make_pptx", "finish"):
        assert unsafe not in READ_ONLY_TOOLS


def test_ingest_never_imports_python_docx() -> None:
    """python-docx pulls in lxml, which re-enables the GIL process-wide."""
    for module in ("kb/ingest.py", "kb/chunking.py", "kb/retrieve.py",
                   "agent/parallel.py"):
        source = (Path(__file__).resolve().parent.parent / module).read_text()
        assert "import docx" not in source
        assert "from docx" not in source


def test_chunking_splits_on_clauses_and_keeps_provenance() -> None:
    text = "\n".join(
        [f"{n}.1 " + " ".join(["word"] * 120) for n in range(1, 12)]
    )
    chunks = chunking._chunk_page(Path("sop.txt"), chunking.Page(3, text))
    assert len(chunks) > 1, "a long document should produce several chunks"
    for chunk in chunks:
        assert chunk.page == 3
        assert chunk.source == "sop.txt"
        assert chunk.id and chunk.tokens > 0
