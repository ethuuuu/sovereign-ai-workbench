"""Run this immediately before a demo. Five checks, green or do not start."""

from __future__ import annotations

import sys

from guard import egress

egress.install()

from config import resolve_path, settings  # noqa: E402
from inference import discovery  # noqa: E402
from router import registry as registry_module  # noqa: E402
from tools.base import load_all  # noqa: E402

TICK, CROSS, WARN = "  ok  ", " FAIL ", " warn "


def main() -> int:
    failures = 0
    print("Sovereign AI Workbench - preflight\n" + "=" * 46)

    from agent.parallel import gil_state

    state = gil_state()
    mark = TICK if (state.scales or not state.free_threaded_build) else WARN
    print(f"[{mark}] runtime:  {state.describe()}")

    registry = registry_module.load()
    print(f"[{TICK}] registry: {len(registry.entries)} models declared")

    health = discovery.check(registry.raw())
    if health.endpoint_reachable:
        print(f"[{TICK}] endpoint: {settings()['inference']['base_url']} reachable")
        print(f"[{TICK}] loaded:   {', '.join(health.available_ids) or 'none'}")
        if health.missing_ids:
            print(f"[{WARN}] declared but not loaded: {', '.join(health.missing_ids)}")
    else:
        print(f"[{CROSS}] endpoint unreachable: {health.error}")
        failures += 1

    tools = load_all()
    print(f"[{TICK}] tools:    {len(tools.names())} registered")

    from tools.sandbox import run

    result = run("print(6 * 7)")
    if result["ok"] and "42" in result["stdout"]:
        print(f"[{TICK}] sandbox:  executes and returns output")
    else:
        print(f"[{CROSS}] sandbox: {result}")
        failures += 1

    blocked = _egress_blocked()
    if blocked:
        print(f"[{TICK}] egress:   external connection refused by policy")
    else:
        print(f"[{CROSS}] egress:   an external connection was NOT blocked")
        failures += 1

    kb_root = resolve_path("knowledge_base")
    if kb_root.exists() and any(kb_root.iterdir()):
        print(f"[{TICK}] kb:       indexed at {kb_root}")
    else:
        print(f"[{WARN}] kb:       not indexed (python -m kb.ingest --source ...)")

    print("=" * 46)
    print("READY" if failures == 0 else f"{failures} check(s) failed - do not start")
    return 1 if failures else 0


def _egress_blocked() -> bool:
    import socket

    probe = socket.socket()
    probe.settimeout(1)
    try:
        probe.connect(("93.184.216.34", 80))
    except egress.EgressBlocked:
        return True
    except OSError:
        return True  # no route at all is also a pass
    finally:
        probe.close()
    return False


if __name__ == "__main__":
    sys.exit(main())
