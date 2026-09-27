"""Proof point 3: the sandbox runs code, catches failure, denies network."""

from __future__ import annotations

from tools.sandbox import run


def test_runs_and_returns_stdout() -> None:
    result = run("print(6 * 7)")
    assert result["ok"]
    assert "42" in result["stdout"]


def test_failure_comes_back_as_a_traceback() -> None:
    result = run("assert 1 == 2, 'deliberate failure'")
    assert not result["ok"]
    assert "AssertionError" in result["stderr"]


def test_network_is_denied_inside_the_sandbox() -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.socket().connect(('93.184.216.34', 80))\n"
        "    print('CONNECTED')\n"
        "except OSError as exc:\n"
        "    print('BLOCKED', exc)\n"
    )
    result = run(code)
    assert "CONNECTED" not in result["stdout"]
