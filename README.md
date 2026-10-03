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
agent/        plan-act-verify loop, context compression, run trace, parallelism
tools/        15 tools: files, sandbox, knowledge base, ingest, deliverables
kb/           knowledge base: parallel ingest, clause-aware chunking, BM25
guard/        egress guard and append-only audit log
service/      FastAPI app, SSE streaming, per-session workspaces
ui/           single-page UI — no build step, no node_modules
scripts/      preflight, demo seeding, run, free-threading benchmark
tests/        router, sandbox and the no-egress proof
```

## Free-threaded Python: where it helps, and where it does not

Free-threaded CPython (3.14t, officially supported since 3.14 under
PEP 779) removes the GIL. It is a real speed-up for pure-Python CPU-bound
work and does nothing at all for anything else, so this project uses it in
exactly one place and says so plainly.

Measured with `scripts/bench_parallel.py` on the project's own chunking
workload, CPython 3.14, 2 cores:

| Build | 1 thread | 2 threads | 4 threads |
| --- | --- | --- | --- |
| standard (GIL) | 0.361s | 0.477s (**0.76x**) | 0.485s (0.74x) |
| free-threaded | 0.339s | 0.203s (**1.67x**) | 0.182s (1.86x) |

Under the GIL, adding threads to this workload makes it 24% *slower*.
Free-threaded, it scales close to linearly. Run it on your own machine
before believing either number.

### Why most of the workbench is untouched

| Path | Bound by | Free threading helps? |
| --- | --- | --- |
| Agent loop | HTTP wait on the model server | No. It is I/O. |
| Sandbox | A child process with its own interpreter | No. Not our GIL. |
| OCR | The `tesseract` binary, out of process | No. |
| Embeddings | HTTP to the embedding server | No. |
| Deliverables | Milliseconds of python-docx | No. Too small to matter. |
| **KB ingest** | **Extract, chunk, hash, tokenise, score** | **Yes. This is the one.** |

A model call takes seconds of GPU time during which Python sits idle.
Removing the GIL does not make a 26B model answer faster. What it does is
turn a 40-minute corpus ingest into a 6-minute one on a 10-core machine.

### The trap that makes this subtle

When the free-threaded interpreter loads a C extension that has not
declared itself safe without the GIL, **it silently turns the GIL back on
for the whole process**. You get no parallelism and you still pay the
free-threaded single-thread overhead.

`python-docx` imports `lxml`, which has not declared it. Verified against
lxml 6.1.3:

```
$ python3.14t -c "import sys, docx; print('GIL on:', sys._is_gil_enabled())"
RuntimeWarning: The global interpreter lock (GIL) has been enabled to load
module 'lxml.etree', which has not declared that it can run safely without
the GIL.
GIL on: True
```

So the design splits along that line:

- **`python -m kb.ingest`** is its own entry point and never imports
  python-docx. `.docx` sources are unzipped with the stdlib in
  `kb/chunking.py` instead. Free threading survives, and ingest scales.
- **The service** imports python-docx because it writes Word files, so it
  runs with the GIL on. That is fine — the service is I/O-bound on the
  model server, so it had nothing to gain.

`scripts/preflight.py` prints which of the three states you are in, and
`agent/parallel.py:gil_state()` is the single place that decides.

### Running ingest free-threaded

```bash
uv python install 3.14t
uv venv --python 3.14t .venv-ingest && source .venv-ingest/bin/activate
pip install pdfplumber PyYAML          # note: no python-docx in this venv
python -m kb.ingest --source /data/sop --collection sop
```

The service keeps running on the standard interpreter. Nothing in
`requirements.txt` changes, and 3.14t is optional everywhere.

### Concurrency that was worth adding anyway

Independent of free threading, the agent loop now runs **read-only tool
calls concurrently** when a model emits several in one turn
(`READ_ONLY_TOOLS` in `agent/loop.py`). Those block on files, sockets and
child processes, all of which release the GIL, so this overlaps on a
standard build too. Anything that writes, executes or finishes stays
strictly sequential, because order is part of its meaning.

## Build status

Runnable today: inference client, registry, router, agent loop, sandbox,
file tools, deliverables, FastAPI service, UI, egress guard, audit log.

Knowledge base: ingest and BM25 retrieval are live. `python -m kb.ingest`
extracts, chunks clause-aware, and writes a citable index; `kb_search`
returns passages with source, page and section. BM25 is implemented in
plain Python — forty lines, no extra dependency for an air-gapped install,
and no C extension that could switch the GIL back on.

Phase 2, interfaces final and stubbed with design notes: dense vectors and
reciprocal-rank fusion in `kb/retrieve.py`, OCR escalation and the vision
model call in `tools/vision.py`, and the Word template merge in
`tools/deliver.py`.

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
