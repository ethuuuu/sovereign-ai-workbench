"""The egress guard.

This module and inference/client.py are the ONLY places in the workbench
that are allowed to touch the network stack. tests/test_no_egress.py fails
the build if any other module imports a networking library.

What it does: wraps socket.socket.connect at process start. A connection to
loopback (or to a host named in policy.yaml) goes through. Anything else
raises EgressBlocked and is recorded with the calling module and a stack
trace, so a dependency quietly phoning home shows up by name rather than as
a mystery.

This is a guard, not a jail. It stops accidental egress -- which is the
realistic failure mode -- and it produces the evidence. A hostile process
could bypass it. The Linux deployment adds a network namespace with no
interfaces, which cannot be bypassed; see docs in README.
"""

from __future__ import annotations

import socket
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import policy

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


class EgressBlocked(RuntimeError):
    """Raised when something tries to open a socket off this machine."""


@dataclass
class EgressState:
    allowed: int = 0
    blocked: int = 0
    allowed_hosts: set[str] = field(default_factory=set)
    violations: list[dict[str, Any]] = field(default_factory=list)
    installed: bool = False


_state = EgressState()
_lock = threading.Lock()
_original_connect = None


def _permitted_hosts() -> set[str]:
    configured = policy().get("egress", {}).get("allowed_hosts", []) or []
    return _LOOPBACK | {str(h) for h in configured}


def _host_of(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _caller() -> str:
    """Name the module that tried to connect, skipping our own frames."""
    for frame in reversed(traceback.extract_stack()[:-2]):
        if "guard/egress" in frame.filename:
            continue
        return f"{frame.filename}:{frame.lineno}"
    return "unknown"


def install() -> None:
    """Patch socket.connect. Call once, before anything opens a connection."""
    global _original_connect
    if _state.installed:
        return

    _original_connect = socket.socket.connect
    permitted = _permitted_hosts()
    on_violation = policy().get("egress", {}).get("on_violation", "block_and_log")

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        host = _host_of(address)
        if host in permitted:
            with _lock:
                _state.allowed += 1
                _state.allowed_hosts.add(host)
            return _original_connect(self, address)

        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "host": host,
            "address": repr(address),
            "caller": _caller(),
        }
        with _lock:
            _state.blocked += 1
            _state.violations.append(record)

        from guard import audit

        audit.write("egress_blocked", record)

        if on_violation == "log_only":
            return _original_connect(self, address)
        raise EgressBlocked(
            f"Outbound connection to {host} blocked by policy.yaml "
            f"(attempted from {record['caller']})"
        )

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    _state.installed = True


def uninstall() -> None:
    """Restore the original connect. Tests only."""
    global _original_connect
    if _original_connect is not None:
        socket.socket.connect = _original_connect  # type: ignore[method-assign]
        _original_connect = None
    _state.installed = False


def snapshot() -> dict[str, Any]:
    """What the sovereignty panel in the UI reads."""
    with _lock:
        return {
            "installed": _state.installed,
            "external_calls": _state.blocked,
            "loopback_calls": _state.allowed,
            "allowed_hosts": sorted(_state.allowed_hosts),
            "violations": list(_state.violations[-20:]),
        }


def reset() -> None:
    with _lock:
        _state.allowed = 0
        _state.blocked = 0
        _state.allowed_hosts.clear()
        _state.violations.clear()
