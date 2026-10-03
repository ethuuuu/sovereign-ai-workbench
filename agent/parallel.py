"""Parallelism, applied only where it is measurably worth it.

Free-threaded CPython (3.14t, PEP 703/779) removes the GIL, so pure-Python
CPU-bound work finally scales across threads. It is not a general speed-up,
and most of this workbench does not benefit:

  agent loop      waits on the model server over HTTP        -> I/O bound
  sandbox         a subprocess with its own interpreter      -> not our GIL
  OCR             shells out to the tesseract binary         -> not our GIL
  embeddings      HTTP to the embedding server               -> I/O bound
  deliverables    milliseconds of python-docx                -> too small

  kb ingest       extract, chunk and hash every document     -> CPU bound,
                  pure Python, embarrassingly parallel          and it scales

Measured on this project's chunking workload (scripts/bench_parallel.py),
2 cores, CPython 3.14:

  standard build   1 thread 0.353s   2 threads 0.459s   0.77x  (threads hurt)
  free-threaded    1 thread 0.312s   2 threads 0.179s   1.74x  (near-linear)

ONE IMPORTANT TRAP. When a C extension has not declared that it is safe
without the GIL, the free-threaded interpreter silently turns the GIL back
on for the whole process. python-docx pulls in lxml, which has not declared
it, so merely importing the deliverable writer re-enables the GIL
everywhere. That is why ingestion is a separate entry point that never
imports python-docx: `python -m kb.ingest` keeps free threading, and the
service process does not need it because it is I/O bound anyway.

gil_state() reports which situation you are in, and preflight prints it.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class GilState:
    free_threaded_build: bool
    gil_currently_enabled: bool
    version: str
    cpu_count: int

    @property
    def scales(self) -> bool:
        """True when CPU-bound Python work will actually use many cores."""
        return self.free_threaded_build and not self.gil_currently_enabled

    def describe(self) -> str:
        if not self.free_threaded_build:
            return (
                f"CPython {self.version} (standard build, GIL). CPU-bound "
                "Python will not scale across threads; this is correct and "
                "costs nothing for I/O-bound work."
            )
        if self.gil_currently_enabled:
            blamed = ", ".join(gil_culprits()[:4]) or "an unidentified module"
            return (
                f"CPython {self.version} free-threaded build, but the GIL was "
                f"RE-ENABLED at runtime by: {blamed}. No parallel speed-up, "
                "and you are paying the free-threaded single-thread overhead "
                "for nothing. Rebuilding that module will not fix it -- see "
                "README, 'Why rebuilding lxml does not help'."
            )
        return (
            f"CPython {self.version} free-threaded, GIL off. CPU-bound Python "
            f"scales across {self.cpu_count} cores."
        )


def gil_state() -> GilState:
    return GilState(
        free_threaded_build=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        gil_currently_enabled=getattr(sys, "_is_gil_enabled", lambda: True)(),
        version=".".join(str(p) for p in sys.version_info[:3]),
        cpu_count=os.cpu_count() or 1,
    )


# Extension modules known to require the GIL, with what to do instead.
# Rebuilding these does not help: whether an extension needs the GIL is a
# declaration in its source (Py_mod_gil / PyUnstable_Module_SetGIL), not a
# property of how it was compiled. lxml already ships a cp314t wheel and
# calls PyUnstable_Module_SetGIL deliberately -- it is telling the truth
# about libxml2's global state, not lagging behind.
KNOWN_GIL_HOLDERS = {
    "lxml.etree": (
        "python-docx and python-pptx depend on it, and openpyxl uses it "
        "opportunistically whenever it is installed. Keep all three out of "
        "the ingest environment."
    ),
}


def gil_culprits() -> list[str]:
    """Which loaded extension modules most likely turned the GIL back on.

    Only meaningful on a free-threaded build where the GIL is on. Returns
    known offenders first, then any other loaded extension module, so a
    new one can be identified without guesswork.
    """
    state = gil_state()
    if not state.free_threaded_build or not state.gil_currently_enabled:
        return []

    known = [name for name in KNOWN_GIL_HOLDERS if name in sys.modules]
    others = []
    for name, module in list(sys.modules.items()):
        if name in known or "." in name and name.rsplit(".", 1)[0] in known:
            continue
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin and origin.endswith((".so", ".pyd", ".dylib")):
            others.append(name)
    return known + sorted(set(others))


def cpu_workers(requested: int | None = None) -> int:
    """Threads for CPU-bound work. One under the GIL -- threads only hurt."""
    if requested is not None:
        return max(1, requested)
    state = gil_state()
    if not state.scales:
        return 1
    return min(state.cpu_count, 16)


def map_cpu(
    fn: Callable[[T], R],
    items: Sequence[T],
    workers: int | None = None,
) -> list[R]:
    """Map over CPU-bound work, in parallel only when that is real.

    Under the GIL this runs serially on purpose: the benchmark above shows
    a thread pool makes this workload 23% SLOWER on a standard build.
    """
    if not items:
        return []
    count = cpu_workers(workers)
    if count == 1 or len(items) == 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(fn, items))


def map_io(
    fn: Callable[[T], R],
    items: Sequence[T],
    workers: int = 8,
) -> list[R]:
    """Map over I/O-bound or subprocess work.

    This one is worth doing on every interpreter: waiting on a socket or a
    child process releases the GIL, so threads overlap properly even on a
    standard build. Free threading changes nothing here.
    """
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


def imap_io(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int = 8,
) -> Iterable[R]:
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        yield from pool.map(fn, items)
    finally:
        pool.shutdown(wait=False)
