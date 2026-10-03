"""The plan-act-verify loop.

Built on the shape of the Nova prototype's run_agent, with four things
added and one thing fixed.

Added:  a plan step, a verify step, a hard step budget, a structured trace.
Fixed:  loop state lived on a function attribute, which made the agent
        non-reentrant -- two concurrent sessions corrupted each other.
        State now lives in RunState.

Repeat handling is softer than the prototype's. Two identical calls inject
a warning into the context; three abort that step and ask for a different
approach, rather than killing the whole run.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent import context, parallel, planner
from agent.trace import Trace
from agent.verifier import verify
from config import policy
from guard import audit
from inference import tool_parse
from inference.client import chat
from router import classify, select
from router.registry import Registry
from tools.base import ToolRegistry

# Tools with no side effects. When a model emits several of these in one
# turn they are run concurrently: each one blocks on a file read, a socket
# or a child process, all of which release the GIL, so this overlaps on a
# standard build too. Free threading is not what makes it work.
READ_ONLY_TOOLS = frozenset(
    {"read_file", "list_dir", "search_files", "kb_search", "read_more",
     "ingest_document", "describe_image"}
)

# Oversized tool results are stored here and fetched in slices by read_more,
# instead of being silently truncated as the prototype did.
LARGE_RESULTS: dict[str, str] = {}

SYSTEM_PROMPT = """You are the Sovereign AI Workbench, an on-premise assistant \
for confidential industrial work. You run entirely inside the organisation's \
network. You have no internet access and must never claim otherwise.

HOW YOU WORK
- Call one tool at a time and read the result before the next call.
- Verify before you report. Execute code before returning it. Recompute a \
number a second way before putting it in a document.
- Cite your sources. A claim drawn from a manual, SOP or uploaded document \
carries its passage id or page number.
- Produce files, not just prose. When the user asks for a note, report, \
calculation or deck, write the actual file.
- Say what you do not know. A missing figure is a bracketed placeholder and \
an open question, never an invention.
- Call finish when the task is done.

Working directory for this session: {workspace}
"""


@dataclass
class RunState:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    steps_taken: int = 0
    call_counts: dict[str, int] = field(default_factory=dict)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    repairs: int = 0

    def signature(self, name: str, args: dict) -> str:
        blob = json.dumps(args, sort_keys=True, default=str)
        return f"{name}:{hashlib.sha1(blob.encode()).hexdigest()[:10]}"


@dataclass
class RunResult:
    answer: str
    task_type: str
    model: str
    route_reason: str
    steps: int
    files: list[str]
    verified: bool
    verification: str
    history: list[dict[str, Any]]


def _store_large(result: str, limit: int) -> str:
    handle = uuid.uuid4().hex[:8]
    LARGE_RESULTS[handle] = result
    head, tail = result[: limit // 2], result[-400:]
    return (
        f"{head}\n\n[... {len(result) - limit} characters omitted. "
        f"Fetch more with read_more(handle='{handle}', start=..., length=...) ...]\n\n"
        f"{tail}"
    )


def run(
    request: str,
    registry: Registry,
    tools: ToolRegistry,
    workspace: str,
    attachments: list[str] | None = None,
    trace: Trace | None = None,
    history: list[dict[str, Any]] | None = None,
) -> RunResult:
    conf = policy().get("agent", {})
    max_steps = int(conf.get("max_steps", 12))
    inline_limit = int(conf.get("tool_result_inline_limit", 4000))

    trace = trace or Trace()
    state = RunState(run_id=trace.run_id)
    audit.write("run_start", {"run": state.run_id, "request": request[:400]})

    # 1. Classify -------------------------------------------------------
    small = next((e for e in registry.entries if "classification" in e.capabilities), None)
    classification = classify.classify(
        request, attachments, small.endpoint_model if small else None
    )
    trace.emit(
        "classify",
        task_type=classification.task_type,
        reason=classification.reason,
        used_model=classification.used_model,
    )

    # 2. Route ----------------------------------------------------------
    route = select.select(
        registry,
        classification.task_type,
        estimated_prompt_tokens=len(request) // 4 + 900,
    )
    trace.emit("route", **route.as_event())

    # 3. Plan -----------------------------------------------------------
    steps = planner.plan(request, route.model.endpoint_model, tools.names())
    if steps:
        trace.emit(
            "plan",
            steps=[{"n": s.n, "action": s.action, "tool": s.tool, "why": s.why} for s in steps],
        )

    # 4. Act ------------------------------------------------------------
    messages: list[dict[str, Any]] = history or [
        {"role": "system", "content": SYSTEM_PROMPT.format(workspace=workspace)}
    ]
    messages.append({"role": "user", "content": request})

    schemas = tools.schemas()
    answer = ""
    files: list[str] = []
    native_tools = True

    while state.steps_taken < max_steps:
        if context.should_compress(messages, route.model.context_window):
            messages = context.compress(messages, route.model.context_window)
            trace.emit("compress", messages=len(messages))

        send = list(messages)
        if not native_tools:
            send[0] = {
                "role": "system",
                "content": send[0]["content"] + tool_parse.instructions(schemas),
            }

        result = chat(
            model=route.model.endpoint_model,
            messages=send,
            tools=schemas if native_tools else None,
            max_tokens=2048,
        )
        message = result["message"]
        calls = message.get("tool_calls") or []

        if not calls and native_tools:
            parsed = tool_parse.parse(message.get("content") or "")
            if parsed:
                native_tools = False
                calls = parsed
                message["tool_calls"] = parsed
                trace.emit("tool_mode", mode="text_fallback")

        messages.append(message)

        if not calls:
            answer = message.get("content") or ""
            break

        prepared = []
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            prepared.append((call, name, args))

        # Several independent reads in one turn overlap; anything that
        # writes, executes or finishes stays strictly sequential, because
        # order is part of its meaning.
        concurrent = (
            len(prepared) > 1
            and all(name in READ_ONLY_TOOLS for _, name, _ in prepared)
        )
        if concurrent:
            trace.emit("parallel_tools", count=len(prepared),
                       tools=[n for _, n, _ in prepared])
            outputs = parallel.map_io(
                lambda item: _invoke(tools, item[1], item[2]), prepared
            )
        else:
            outputs = None

        for index, (call, name, args) in enumerate(prepared):

            signature = state.signature(name, args)
            state.call_counts[signature] = state.call_counts.get(signature, 0) + 1
            repeats = state.call_counts[signature]

            if outputs is not None:
                output = outputs[index]
            elif repeats >= 3:
                output = (
                    f"REFUSED: '{name}' has been called three times with the "
                    "same arguments and returned the same thing. Try a "
                    "different approach, or call finish and report what you "
                    "have."
                )
            elif repeats == 2:
                output = _invoke(tools, name, args)
                output = (
                    "[Note: identical call repeated. Read the result before "
                    "calling again.]\n" + output
                )
            else:
                output = _invoke(tools, name, args)

            state.steps_taken += 1
            state.tool_log.append({"tool": name, "args": args, "result": output})
            trace.emit(
                "tool",
                step=state.steps_taken,
                tool=name,
                args=args,
                preview=output[:300],
            )

            if name in {"make_docx", "make_xlsx", "make_pptx"} and "Wrote" in output:
                filename = args.get("filename")
                if filename:
                    files.append(filename)

            if name == "finish":
                answer = args.get("summary", "") or "Task complete."
                files.extend(f for f in (args.get("files") or []) if f not in files)

            if len(output) > inline_limit:
                output = _store_large(output, inline_limit)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", f"call_{state.steps_taken}"),
                    "content": output,
                }
            )

        if answer:
            break

    else:
        answer = answer or (
            f"I reached the {max_steps}-step budget for this task. Here is "
            "what I completed; ask me to continue if you want the rest."
        )
        trace.emit("budget_exhausted", steps=state.steps_taken)

    # 5. Verify ---------------------------------------------------------
    verdict = verify(classification.task_type, answer, state.tool_log)
    trace.emit("verify", passed=verdict.passed, detail=verdict.detail)

    trace.emit("done", steps=state.steps_taken, files=files)
    audit.write(
        "run_end",
        {
            "run": state.run_id,
            "steps": state.steps_taken,
            "verified": verdict.passed,
            "files": files,
        },
    )

    return RunResult(
        answer=answer,
        task_type=classification.task_type,
        model=route.model.id,
        route_reason=route.reason,
        steps=state.steps_taken,
        files=files,
        verified=verdict.passed,
        verification=verdict.detail,
        history=messages,
    )


def _invoke(tools: ToolRegistry, name: str, args: dict) -> str:
    tool = tools.get(name)
    if tool is None:
        return f"Unknown tool '{name}'. Available: {', '.join(tools.names())}"
    try:
        return str(tool.fn(args))
    except Exception as exc:  # noqa: BLE001 - the model should see and recover
        audit.write("tool_error", {"tool": name, "error": str(exc)})
        return f"Tool '{name}' raised {type(exc).__name__}: {exc}"
