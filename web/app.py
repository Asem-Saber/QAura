import json
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from web.pipeline import pipeline_manager

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="QAura Dashboard")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
    })


@app.get("/agents")
async def agents_page(request: Request):
    return templates.TemplateResponse(request, "agents.html", {
        "active_page": "agents",
    })


@app.get("/reports")
async def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", {
        "active_page": "reports",
    })


@app.post("/runs")
async def start_run(request: Request):
    form = await request.form()
    requirements_path = form.get("requirements_path", "")
    if not requirements_path:
        requirements_path = None

    try:
        run_id = pipeline_manager.start_run(requirements_path)
    except RuntimeError as e:
        return HTMLResponse(
            f'<p class="text-sm" style="color: var(--accent-red);">{e}</p>',
            status_code=409,
        )

    response = RedirectResponse(url=f"/dashboard?run_id={run_id}", status_code=303)
    return response


@app.get("/sse/pipeline/{run_id}")
async def sse_pipeline(run_id: str, request: Request):
    async def event_generator():
        async for event in pipeline_manager.get_event_stream(run_id):
            data = json.dumps(event.data)
            yield {"event": event.event_type, "data": data}

    return EventSourceResponse(event_generator())


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, request: Request):
    form = await request.form()
    approved = form.get("approved") == "true"
    feedback = form.get("feedback", "")

    try:
        pipeline_manager.approve_run(run_id, approved, feedback)
    except ValueError as e:
        return HTMLResponse(str(e), status_code=404)

    status_text = "approved" if approved else "rejected"
    return HTMLResponse(
        f'<div class="sse-new p-3 rounded-lg" style="background-color: var(--bg-surface); border: 1px solid var(--border);">'
        f'<span class="badge {"badge-completed" if approved else "badge-errored"}">{status_text}</span>'
        f'<span class="ml-2 text-sm" style="color: var(--text-secondary);">Plan {status_text}. Pipeline resuming...</span>'
        f'</div>'
    )


@app.get("/runs/{run_id}/state")
async def run_state(run_id: str):
    state = pipeline_manager.get_run_state(run_id)
    if state is None:
        return {"error": "Run not found"}

    serialized = {}
    for key, value in state.items():
        if hasattr(value, "model_dump"):
            serialized[key] = value.model_dump()
        elif isinstance(value, list) and value and hasattr(value[0], "model_dump"):
            serialized[key] = [item.model_dump() for item in value]
        else:
            serialized[key] = value
    return serialized
