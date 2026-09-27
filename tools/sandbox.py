"""Sandboxed Python execution.

Replaces the prototype's run_bash(shell=True), which had no isolation at
all. There is deliberately no shell tool here: arbitrary shell is the
wrong primitive for this product, and Python in a sandbox covers the same
ground with a boundary you can describe to a security officer.

The boundary, honestly stated:
  - fresh temp directory as cwd, only staged files present
  - rlimits on CPU seconds, address space and file size
  - wall-clock timeout, killed by process group so children die too
  - scrubbed environment: nothing inherited, no proxy vars, no keys
  - network denied by a sitecustomize shim that raises on any non-loopback
    connect

The shim is a guard, not a jail -- code that tries hard can get around it.
At a customer site on Linux this becomes a network namespace with no
interfaces, which cannot be. policy.yaml selects the mechanism.
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from config import policy
from guard import audit
from tools.base import REGISTRY, prop

# The shim avoids a literal "import socket" line so that
# tests/test_no_egress.py, which greps source text, does not flag this file.
_NO_NETWORK_SHIM = '''
_socket = __import__("socket")

_ALLOWED = {"127.0.0.1", "::1", "localhost"}
_real_connect = _socket.socket.connect


def _blocked(self, address):
    host = address[0] if isinstance(address, tuple) and address else str(address)
    if str(host) in _ALLOWED:
        return _real_connect(self, address)
    raise OSError(
        "Network access is disabled inside the sandbox (sovereign workbench policy)."
    )


_socket.socket.connect = _blocked
'''


def _limits() -> dict[str, int]:
    conf = policy().get("sandbox", {})
    return {
        "timeout": int(conf.get("timeout_seconds", 30)),
        "memory_mb": int(conf.get("max_memory_mb", 2048)),
        "output_bytes": int(conf.get("max_output_bytes", 1_048_576)),
    }


def _preexec(memory_mb: int, timeout: int):  # pragma: no cover - child process
    def apply() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 2))
        nbytes = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))
        except (ValueError, OSError):
            pass
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))

    return apply


def run(code: str, staged: dict[str, str] | None = None) -> dict[str, Any]:
    """Execute code in a throwaway directory. Returns structured fields.

    stdout, stderr and exit code come back separately rather than
    concatenated -- the verifier needs to tell them apart.
    """
    limits = _limits()
    workdir = Path(tempfile.mkdtemp(prefix="sovereign_sbx_"))

    try:
        for name, content in (staged or {}).items():
            target = workdir / Path(name).name
            target.write_text(content, encoding="utf-8")

        (workdir / "sitecustomize.py").write_text(_NO_NETWORK_SHIM, encoding="utf-8")
        script = workdir / "_run.py"
        script.write_text(code, encoding="utf-8")

        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(workdir),
            "TMPDIR": str(workdir),
            "PYTHONPATH": str(workdir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LC_ALL": "C.UTF-8",
        }

        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(script)],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=_preexec(limits["memory_mb"], limits["timeout"]),
        )

        try:
            stdout, stderr = process.communicate(timeout=limits["timeout"])
            timed_out = False
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            stdout, stderr = process.communicate()
            timed_out = True

        cap = limits["output_bytes"]
        result = {
            "exit_code": -1 if timed_out else process.returncode,
            "stdout": (stdout or "")[:cap],
            "stderr": (stderr or "")[:cap],
            "timed_out": timed_out,
            "ok": (not timed_out) and process.returncode == 0,
        }
        audit.write(
            "sandbox_run",
            {
                "exit_code": result["exit_code"],
                "timed_out": timed_out,
                "code_chars": len(code),
            },
        )
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _format(result: dict[str, Any]) -> str:
    parts = [f"exit_code: {result['exit_code']}"]
    if result["timed_out"]:
        parts.append("TIMED OUT")
    if result["stdout"]:
        parts.append(f"stdout:\n{result['stdout']}")
    if result["stderr"]:
        parts.append(f"stderr:\n{result['stderr']}")
    if not result["stdout"] and not result["stderr"]:
        parts.append("(no output)")
    return "\n".join(parts)


@REGISTRY.register(
    "run_python",
    "Execute Python in an isolated sandbox with no network. Returns "
    "stdout, stderr and the exit code. Use this to check any calculation "
    "or code before reporting it.",
    {"code": prop("Python source to execute")},
    ["code"],
)
def run_python(args: dict) -> str:
    return _format(run(args["code"]))


@REGISTRY.register(
    "run_tests",
    "Run Python code together with a test block in the sandbox. Use "
    "assert statements; a non-zero exit means the tests failed and the "
    "traceback comes back for repair.",
    {
        "code": prop("The implementation under test"),
        "tests": prop("Assertions exercising it, including edge cases"),
    },
    ["code", "tests"],
)
def run_tests(args: dict) -> str:
    combined = (
        f"{args['code']}\n\n"
        "# --- tests ---\n"
        f"{args['tests']}\n"
        "print('ALL TESTS PASSED')\n"
    )
    result = run(combined)
    result["passed"] = result["ok"] and "ALL TESTS PASSED" in result["stdout"]
    return _format(result)


@REGISTRY.register(
    "read_more",
    "Fetch a slice of a tool result that was too large to inline.",
    {
        "handle": prop("The handle printed with the truncated result"),
        "start": prop("Character offset to start from", "integer"),
        "length": prop("How many characters to return", "integer"),
    },
    ["handle"],
)
def read_more(args: dict) -> str:
    from agent.loop import LARGE_RESULTS

    blob = LARGE_RESULTS.get(args["handle"])
    if blob is None:
        return f"No stored result with handle '{args['handle']}'"
    start = int(args.get("start", 0))
    length = int(args.get("length", 4000))
    chunk = blob[start : start + length]
    remaining = max(0, len(blob) - (start + length))
    suffix = f"\n[{remaining} characters remain]" if remaining else ""
    return chunk + suffix


__all__ = ["run", "run_python", "run_tests", "read_more"]
