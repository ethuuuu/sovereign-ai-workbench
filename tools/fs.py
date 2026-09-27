"""File tools, jailed to the roots declared in policy.yaml.

Every path argument is fully resolved, symlinks included, before use. A
path outside the roots returns a refusal the model can read and correct
rather than raising. There is no delete tool.
"""

from __future__ import annotations

from pathlib import Path

from config import REPO_ROOT, policy
from guard import audit
from tools.base import REGISTRY, prop


class PathRefused(Exception):
    pass


def allowed_roots() -> list[Path]:
    roots = []
    for raw in policy().get("files", {}).get("roots", []) or []:
        path = Path(raw)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        roots.append(path.resolve())
    return roots


def safe_path(raw: str, session_root: Path | None = None) -> Path:
    """Resolve a model-supplied path and prove it is inside a root."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        base = session_root or (allowed_roots()[0] if allowed_roots() else REPO_ROOT)
        candidate = base / candidate

    resolved = candidate.resolve()
    roots = allowed_roots()
    if session_root:
        roots.append(session_root.resolve())

    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise PathRefused(
        f"Path '{raw}' resolves outside the permitted roots "
        f"({', '.join(str(r) for r in roots)}). Use a path inside the workspace."
    )


@REGISTRY.register(
    "read_file",
    "Read a UTF-8 text file from the workspace or knowledge base.",
    {"path": prop("Path to the file")},
    ["path"],
)
def read_file(args: dict) -> str:
    try:
        path = safe_path(args["path"])
    except PathRefused as exc:
        return f"REFUSED: {exc}"
    if not path.is_file():
        return f"No such file: {args['path']}"

    limit = policy().get("files", {}).get("max_read_bytes", 4_194_304)
    data = path.read_bytes()[: int(limit)]
    audit.write("file_read", {"path": str(path), "bytes": len(data)})
    return data.decode("utf-8", errors="replace")


@REGISTRY.register(
    "write_file",
    "Write a text file into the workspace. Creates parent folders.",
    {"path": prop("Path to write"), "content": prop("Full file contents")},
    ["path", "content"],
)
def write_file(args: dict) -> str:
    try:
        path = safe_path(args["path"])
    except PathRefused as exc:
        return f"REFUSED: {exc}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.get("content", ""), encoding="utf-8")
    audit.write("file_write", {"path": str(path), "bytes": len(args.get("content", ""))})
    return f"Wrote {len(args.get('content', ''))} characters to {path.name}"


@REGISTRY.register(
    "list_dir",
    "List files and folders in a workspace directory.",
    {"path": prop("Directory path")},
    ["path"],
)
def list_dir(args: dict) -> str:
    try:
        path = safe_path(args["path"])
    except PathRefused as exc:
        return f"REFUSED: {exc}"
    if not path.is_dir():
        return f"Not a directory: {args['path']}"
    rows = []
    for entry in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
        kind = "file" if entry.is_file() else "dir "
        size = f"{entry.stat().st_size:>9}" if entry.is_file() else " " * 9
        rows.append(f"{kind} {size}  {entry.name}")
    return "\n".join(rows) or "(empty)"


@REGISTRY.register(
    "search_files",
    "Find files matching a glob pattern under a directory.",
    {"path": prop("Root directory"), "pattern": prop("Glob, e.g. *.csv")},
    ["path", "pattern"],
)
def search_files(args: dict) -> str:
    try:
        path = safe_path(args["path"])
    except PathRefused as exc:
        return f"REFUSED: {exc}"
    matches = sorted(str(m) for m in path.rglob(args["pattern"]))[:50]
    return "\n".join(matches) or "No matches"
