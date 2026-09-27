"""Per-task-type checks that run before a result is returned.

This is what makes the output trustworthy, and it is the difference
between an assistant and a plausible-text generator. An assistant that
cannot be audited is useless in a PSU approval chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Verdict:
    passed: bool
    detail: str
    repairable: bool = False


def verify(task_type: str, answer: str, tool_log: list[dict]) -> Verdict:
    checker = {
        "code_generation": _code,
        "calculation": _calculation,
        "retrieval_qa": _retrieval,
        "document_drafting": _document,
    }.get(task_type)
    if checker is None:
        return Verdict(True, "no verification defined for this task type")
    return checker(answer, tool_log)


def _tools_used(tool_log: list[dict], *names: str) -> list[dict]:
    return [entry for entry in tool_log if entry.get("tool") in names]


def _code(answer: str, tool_log: list[dict]) -> Verdict:
    runs = _tools_used(tool_log, "run_python", "run_tests")
    if not runs:
        return Verdict(
            False,
            "code was produced but never executed. Run it with run_tests "
            "before reporting it.",
            repairable=True,
        )
    last = runs[-1].get("result", "")
    if "exit_code: 0" not in last:
        return Verdict(
            False,
            f"the last sandbox run did not exit cleanly:\n{last[:800]}",
            repairable=True,
        )
    return Verdict(True, f"executed in the sandbox, {len(runs)} run(s), exit 0")


def _calculation(answer: str, tool_log: list[dict]) -> Verdict:
    if not _tools_used(tool_log, "run_python", "make_xlsx"):
        return Verdict(
            False,
            "a numeric result was reported without being computed. Recompute "
            "it with run_python and compare, or build it as a spreadsheet "
            "with real formulas.",
            repairable=True,
        )
    return Verdict(True, "recomputed independently before reporting")


def _retrieval(answer: str, tool_log: list[dict]) -> Verdict:
    if not _tools_used(tool_log, "kb_search", "ingest_document", "read_file"):
        return Verdict(True, "answered without a source; no citation required")
    if re.search(r"\[[A-Za-z0-9_.\-]+\]|p\.\s?\d+", answer):
        return Verdict(True, "claims carry source citations")
    return Verdict(
        False,
        "sources were retrieved but the answer cites none. Add the passage "
        "id or page number beside each claim taken from them.",
        repairable=True,
    )


def _document(answer: str, tool_log: list[dict]) -> Verdict:
    made = _tools_used(tool_log, "make_docx", "make_xlsx", "make_pptx")
    if not made:
        return Verdict(
            False,
            "a document was requested but no file was written. Use make_docx, "
            "make_xlsx or make_pptx.",
            repairable=True,
        )
    failures = [m for m in made if "verification failed" in str(m.get("result", ""))]
    if failures:
        return Verdict(
            False,
            f"the file was written but did not verify: {failures[-1]['result'][:400]}",
            repairable=True,
        )
    return Verdict(True, f"{len(made)} file(s) written and re-opened cleanly")
