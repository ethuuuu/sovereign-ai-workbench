"""The parallelism decisions, pinned down.

These pass on a standard interpreter too -- that is the point. Nothing in
the project may REQUIRE free threading; it only exploits it when present.
"""

from __future__ import annotations

import sys
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


def test_ingest_import_graph_stays_free_of_lxml() -> None:
    """The whole point of kb/chunking.py reading .docx with the stdlib.

    openpyxl is the subtle one: it is lxml-free until lxml happens to be
    installed, at which point it uses it and the GIL comes back on. So the
    ingest environment must not contain lxml at all.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; sys.path.insert(0, %r);"
        "import kb.ingest, kb.chunking, kb.retrieve;"
        "bad=[m for m in sys.modules if m.startswith('lxml') or m=='docx' "
        "or m=='pptx' or m=='openpyxl'];"
        "print(','.join(sorted(bad)))" % str(root)
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=root
    )
    assert out.returncode == 0, out.stderr
    assert not out.stdout.strip(), (
        f"ingest pulled in GIL-holding modules: {out.stdout.strip()}"
    )


def _import_graph(statement: str) -> set[str]:
    """Which GIL-holding modules a given import pulls in. Subprocess, so it
    cannot pass by accident because of what this test file already loaded."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; sys.path.insert(0, %r); %s; "
        "print(','.join(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'lxml','docx','pptx','openpyxl'})))" % (str(root), statement)
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=root
    )
    assert out.returncode == 0, out.stderr
    return {m for m in out.stdout.strip().split(",") if m}


def test_loading_every_agent_tool_pulls_in_no_gil_holder() -> None:
    """The agent process must stay free-threadable even with make_docx
    registered. The writers live in scripts/deliver_worker.py instead."""
    pulled = _import_graph("from tools.base import load_all; load_all()")
    assert not pulled, f"the agent process would lose free threading to: {pulled}"


def test_the_worker_is_the_only_place_the_writers_are_imported() -> None:
    root = Path(__file__).resolve().parent.parent
    worker = (root / "scripts" / "deliver_worker.py").read_text()
    assert "from docx import" in worker and "from pptx import" in worker

    for module in ("tools/deliver.py", "tools/isolated.py", "agent/loop.py",
                   "service/app.py"):
        source = (root / module).read_text()
        for banned in ("import docx", "from docx", "import pptx", "from pptx",
                       "import openpyxl", "from openpyxl", "import lxml"):
            assert banned not in source, f"{module} imports {banned}"


def test_isolation_only_happens_when_it_buys_something() -> None:
    from tools.isolated import should_isolate

    assert should_isolate() == parallel.gil_state().scales


def test_known_gil_holders_are_documented() -> None:
    for name, advice in parallel.KNOWN_GIL_HOLDERS.items():
        assert name and advice


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
