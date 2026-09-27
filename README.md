# Sovereign AI Workbench

An on-premise agentic AI workbench for confidential industrial work, built
on open-weight multimodal models. Refineries, PSUs, defence-linked units
and government offices generate a lot of routine knowledge work on material
that cannot go to a cloud assistant. This runs the same kind of assistant
entirely inside the organisation's own network.

Built for Smart India Hackathon 2026.

## The claim, and how it is proved

| Claim | Evidence in this repo |
| --- | --- |
| Model auto-selection across task types | `router/` — a YAML registry of capability tags; every decision returns a reason string printed in the UI and written to the audit log |
| Agentic, not a chat wrapper | `agent/loop.py` — plan, act, verify, with a step budget and a structured trace |
| Code is verified, not just generated | `tools/sandbox.py` + `agent/verifier.py` — executed in an isolated subprocess before it is returned |
| Real deliverables | `tools/deliver.py` — Word, Excel and PowerPoint, re-opened and checked after writing |
| No external calls, ever | `guard/egress.py`, `guard/audit.py`, `tests/test_no_egress.py` |

## The one rule the design rests on

**No module imports a networking library except `inference/client.py`.**
That is a single checkable invariant, and `tests/test_no_egress.py` fails
the build if it is broken. It is what makes the sovereignty claim
auditable rather than rhetorical.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Point config/settings.yaml at your local /v1 endpoint, then:
python scripts/preflight.py      # five checks; green or do not start
./scripts/run.sh                 # http://127.0.0.1:8080
```

The inference layer speaks the OpenAI-compatible `/v1` protocol and nothing
else. vLLM on a CUDA server, MLX on Apple silicon, llama.cpp or Ollama on a
workstation all work. Moving between them is a base-URL change in
`config/settings.yaml`; no code changes.

## Adding a model

Edit `config/models.yaml`:

```yaml
  - id: my-new-model
    endpoint_model: <exact id from GET /v1/models>
    capabilities: [code_generation, structured_output]
    context_window: 131072
    speed_class: fast
```

That is the whole process. The router picks it up on restart, and
`inference/discovery.py` marks it unavailable (rather than crashing) if the
weights are not loaded on the endpoint.

## Layout

```
config/       settings.yaml, models.yaml, policy.yaml — everything site-specific
inference/    the ONLY network-facing code: /v1 client, discovery, tool-call fallback
router/       model registry, task classification, selection with reasons
agent/        plan-act-verify loop, context compression, run trace
tools/        15 tools: files, sandbox, knowledge base, ingest, deliverables
kb/           local knowledge base: ingest, store, hybrid retrieval  [phase 2]
guard/        egress guard and append-only audit log
service/      FastAPI app, SSE streaming, per-session workspaces
ui/           single-page UI — no build step, no node_modules
scripts/      preflight, demo seeding, run
tests/        router, sandbox and the no-egress proof
```

## Build status

Runnable today: inference client, registry, router, agent loop, sandbox,
file tools, deliverables, FastAPI service, UI, egress guard, audit log.

Phase 2, interfaces final and stubbed with design notes:
`kb/` (ingest, embed, hybrid retrieve), OCR escalation and the vision model
call in `tools/vision.py`, and the Word template merge in `tools/deliver.py`.

## Security posture, stated honestly

The egress guard patches `socket.connect` at process start. It stops
accidental egress — a dependency with telemetry, which is the realistic
failure mode — and it produces the evidence. A hostile process could get
around it.

The sandbox applies rlimits, a scrubbed environment, a process-group kill
on timeout and a no-network shim. On macOS the shim is a guard, not a jail.
The Linux deployment at a customer site adds a network namespace with no
interfaces, which cannot be bypassed; `config/policy.yaml` selects the
mechanism.

Model weights are fetched once on a staging machine, hashed, and moved to
the air-gapped host on removable media. The workbench itself downloads
nothing, and `settings.yaml` contains no model-hub URL.

For a demo, turn Wi-Fi off. Nothing beats it.

## Licence

To be decided before publication.
