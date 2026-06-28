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

AGENT_COLORS = {
    "test_architect": "#a78bfa",
    "unit_test_gen": "#4ade80",
    "integration_test_gen": "#60a5fa",
    "e2e_gen": "#fbbf24",
    "execution_agent": "#f97316",
    "reporting_agent": "#06b6d4",
    "defect_intelligence_agent": "#f87171",
    "self_healing_agent": "#e879f9",
    "human_approval": "#8b8fa3",
    "system": "#8b8fa3",
}

AGENT_DISPLAY_NAMES = {
    "test_architect": "Test Architect",
    "unit_test_gen": "Unit Generator",
    "integration_test_gen": "Integration Gen",
    "e2e_gen": "E2E Generator",
    "execution_agent": "Execution Runner",
    "reporting_agent": "Reporting",
    "defect_intelligence_agent": "Defect Intelligence",
    "self_healing_agent": "Self-Healing",
    "human_approval": "HITL Approval",
    "system": "System",
}


def _render_sse_event(event, templates_instance) -> dict:
    """Render a PipelineEvent into an SSE dict with event type and HTML data."""
    etype = event.event_type
    data = event.data

    if etype == "agent_log":
        agent = data.get("agent", "system")
        ts_raw = data.get("timestamp", "")
        ts_short = ts_raw[11:19] if len(ts_raw) > 19 else ts_raw
        html = templates_instance.get_template("partials/timeline/log_entry.html").render(
            timestamp_short=ts_short,
            agent=agent,
            agent_display=AGENT_DISPLAY_NAMES.get(agent, agent),
            agent_color=AGENT_COLORS.get(agent, "#8b8fa3"),
            message=data.get("message", ""),
            status="running",
            pills=[f"tool:{tc['name']}" for tc in data.get("tool_calls", [])],
        )
        return {"event": etype, "data": html}

    elif etype == "phase_change":
        status = data.get("status", "running")
        html = templates_instance.get_template("partials/timeline/phase_badge.html").render(
            phase=data.get("phase", ""),
            status=status,
        )
        return {"event": etype, "data": html}

    elif etype == "plan_ready":
        html = templates_instance.get_template("partials/timeline/approval_card.html").render(
            plan=data.get("plan", {}),
            run_id=pipeline_manager.current_run_id,
        )
        return {"event": etype, "data": html}

    elif etype == "run_complete":
        html = '<div class="flex items-center gap-2 px-4 py-2 rounded-lg" style="background-color: var(--bg-surface); border: 1px solid var(--border);"><span class="badge badge-completed">completed</span><span class="text-sm font-medium">Pipeline Complete</span></div>'
        return {"event": etype, "data": html}

    elif etype == "stats_update":
        html = templates_instance.get_template("partials/summary/run_summary.html").render(**data)
        return {"event": etype, "data": html}

    return {"event": etype, "data": json.dumps(data)}


@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request):
    run_id = request.query_params.get("run_id") or pipeline_manager.current_run_id
    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "run_id": run_id if pipeline_manager.is_running else None,
        "phase": pipeline_manager.current_phase,
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
            yield _render_sse_event(event, templates)

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
