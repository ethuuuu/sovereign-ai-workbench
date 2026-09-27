"""FastAPI service.

The egress guard is installed before anything else imports a client, so a
dependency that phones home at import time is caught too.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any

from guard import egress

egress.install()  # must run before the inference client is constructed

from fastapi import FastAPI, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from agent import loop  # noqa: E402
from agent.trace import Trace  # noqa: E402
from config import REPO_ROOT, settings  # noqa: E402
from guard import audit  # noqa: E402
from inference import discovery  # noqa: E402
from router import registry as registry_module  # noqa: E402
from service import schemas, sessions  # noqa: E402
from tools.base import load_all  # noqa: E402

app = FastAPI(title="Sovereign AI Workbench", version="0.1.0")

REGISTRY = registry_module.load()
TOOLS = load_all()


@app.on_event("startup")
def startup() -> None:
    health = discovery.check(REGISTRY.raw())
    REGISTRY.mark_availability(health.available_ids)
    audit.write(
        "service_start",
        {
            "endpoint": settings()["inference"]["base_url"],
            "reachable": health.endpoint_reachable,
            "available": health.available_ids,
            "missing": health.missing_ids,
            "tools": TOOLS.names(),
        },
    )


@app.post("/api/session", response_model=schemas.SessionResponse)
def create_session() -> schemas.SessionResponse:
    session = sessions.create()
    audit.set_session(session.id)
    return schemas.SessionResponse(
        session_id=session.id, workspace=str(session.root), created=session.created
    )


@app.get("/api/models", response_model=schemas.ModelsResponse)
def list_models() -> schemas.ModelsResponse:
    health = discovery.check(REGISTRY.raw())
    REGISTRY.mark_availability(health.available_ids)
    return schemas.ModelsResponse(
        endpoint=settings()["inference"]["base_url"],
        reachable=health.endpoint_reachable,
        error=health.error,
        models=[
            schemas.ModelInfo(
                id=e.id,
                endpoint_model=e.endpoint_model,
                capabilities=sorted(e.capabilities),
                context_window=e.context_window,
                speed_class=e.speed_class,
                default=e.default,
                available=e.available,
            )
            for e in REGISTRY.entries
        ],
    )


@app.get("/api/egress", response_model=schemas.EgressResponse)
def egress_state() -> schemas.EgressResponse:
    return schemas.EgressResponse(**egress.snapshot())


@app.post("/api/upload")
async def upload(session_id: str, file: UploadFile) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown session")
    name = Path(file.filename or "upload.bin").name
    target = session.uploads / name
    target.write_bytes(await file.read())
    audit.write("upload", {"session": session_id, "name": name,
                           "bytes": target.stat().st_size})
    return {"name": name, "path": str(target), "bytes": target.stat().st_size}


@app.get("/api/files/{session_id}")
def list_files(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown session")
    return {"files": sessions.deliverables(session)}


@app.get("/api/download/{session_id}/{name}")
def download(session_id: str, name: str) -> FileResponse:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown session")
    path = session.deliverables / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "No such file")
    return FileResponse(path, filename=path.name)


@app.get("/api/audit/{session_id}")
def session_audit(session_id: str) -> dict[str, Any]:
    return {"events": audit.read_session(session_id)}


@app.post("/api/kb/search")
def kb_search(body: schemas.KbSearchRequest) -> dict[str, Any]:
    from tools.kb import kb_search as run_search

    return {"result": run_search({"query": body.query, "top_k": body.top_k})}


@app.post("/api/chat")
async def chat_stream(body: schemas.ChatRequest) -> StreamingResponse:
    """Run the agent, streaming every trace event as it happens."""
    session = sessions.get_or_create(body.session_id)
    audit.set_session(session.id)

    events: queue.Queue = queue.Queue()
    trace = Trace()
    trace.subscribe(events.put)

    def work() -> None:
        try:
            result = loop.run(
                request=body.message,
                registry=REGISTRY,
                tools=TOOLS,
                workspace=str(session.root),
                attachments=body.attachments,
                trace=trace,
                history=session.history or None,
            )
            session.history = result.history
            session.snapshot()
            events.put(
                {
                    "kind": "answer",
                    "text": result.answer,
                    "model": result.model,
                    "task_type": result.task_type,
                    "steps": result.steps,
                    "files": result.files,
                    "verified": result.verified,
                    "verification": result.verification,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser
            audit.write("run_failed", {"error": str(exc)})
            events.put({"kind": "error", "message": str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def stream():
        yield f"data: {json.dumps({'kind': 'session', 'session_id': session.id})}\n\n"
        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/", StaticFiles(directory=REPO_ROOT / "ui", html=True), name="ui")
