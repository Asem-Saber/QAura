import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from web.pipeline import pipeline_manager

_logger = logging.getLogger("uvicorn.error")

WEB_DIR = Path(__file__).resolve().parent


def _windows_exception_handler(loop, context):
    exc = context.get("exception")
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 87:
        _logger.debug("Suppressed ProactorEventLoop WinError 87")
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def lifespan(app):
    if sys.platform == "win32":
        asyncio.get_running_loop().set_exception_handler(_windows_exception_handler)
    yield


app = FastAPI(title="QAura Dashboard", lifespan=lifespan)

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
    agents = {
        "test_architect": {"display": "Test Architect", "color": AGENT_COLORS["test_architect"]},
        "unit_test_gen": {"display": "Unit Generator", "color": AGENT_COLORS["unit_test_gen"]},
        "integration_test_gen": {"display": "Integration Gen", "color": AGENT_COLORS["integration_test_gen"]},
        "e2e_gen": {"display": "E2E Generator", "color": AGENT_COLORS["e2e_gen"]},
        "execution_agent": {"display": "Execution Runner", "color": AGENT_COLORS["execution_agent"]},
        "reporting_agent": {"display": "Reporting", "color": AGENT_COLORS["reporting_agent"]},
        "defect_intelligence_agent": {"display": "Defect Intelligence", "color": AGENT_COLORS["defect_intelligence_agent"]},
        "self_healing_agent": {"display": "Self-Healing", "color": AGENT_COLORS["self_healing_agent"]},
    }

    first_agent_key = next(iter(agents))
    first_agent_logs = pipeline_manager.get_agent_logs(first_agent_key)

    return templates.TemplateResponse(request, "agents.html", {
        "active_page": "agents",
        "agents": agents,
        "first_agent": first_agent_key if first_agent_logs else None,
        "agent_display": agents[first_agent_key]["display"],
        "agent_color": agents[first_agent_key]["color"],
        "agent_status": "completed" if first_agent_logs else "idle",
        "logs": first_agent_logs,
    })


@app.get("/partials/agents/{agent_name}/logs")
async def agent_logs_partial(agent_name: str):
    logs = pipeline_manager.get_agent_logs(agent_name)
    display = AGENT_DISPLAY_NAMES.get(agent_name, agent_name)
    color = AGENT_COLORS.get(agent_name, "#8b8fa3")
    status = "completed" if logs else "idle"

    if pipeline_manager.is_running and pipeline_manager.current_agent == agent_name:
        status = "running"

    html = templates.get_template("partials/agents/agent_tab.html").render(
        agent_display=display,
        agent_color=color,
        agent_status=status,
        logs=logs,
    )
    return HTMLResponse(html)


@app.get("/reports")
async def reports_page(request: Request):
    run_id = pipeline_manager.current_run_id
    state = pipeline_manager.get_run_state(run_id) if run_id else None

    stats = None
    coverage = None
    report = None
    defect_analyses = []
    healing_actions = []
    anomaly_count = 0
    healing_success = 0
    healing_total = 0

    if state:
        stats_raw = state.get("execution_summary")
        stats = stats_raw.model_dump() if hasattr(stats_raw, "model_dump") else stats_raw

        cov_raw = state.get("coverage_assessment")
        coverage = cov_raw.model_dump() if hasattr(cov_raw, "model_dump") else cov_raw

        report_raw = state.get("qa_report")
        report = report_raw.model_dump() if hasattr(report_raw, "model_dump") else report_raw

        defect_analyses_raw = state.get("defect_analyses", [])
        defect_analyses = [a.model_dump() if hasattr(a, "model_dump") else a for a in defect_analyses_raw]

        healing_actions_raw = state.get("healing_actions", [])
        healing_actions = [a.model_dump() if hasattr(a, "model_dump") else a for a in healing_actions_raw]

        anomaly_count = len(state.get("anomaly_reports", []))
        healing_total = len(healing_actions)
        healing_success = sum(1 for a in healing_actions if a.get("success", False))

    return templates.TemplateResponse(request, "reports.html", {
        "active_page": "reports",
        "stats": stats,
        "coverage": coverage,
        "report": report,
        "defect_analyses": defect_analyses,
        "healing_actions": healing_actions,
        "anomaly_count": anomaly_count,
        "healing_success": healing_success,
        "healing_total": healing_total,
    })


@app.get("/partials/new-run-form")
async def new_run_form(request: Request):
    html = '''
    <div class="fixed inset-0 z-50 flex items-center justify-center" style="background-color: rgba(0,0,0,0.6);">
        <div class="card p-6 w-96" style="background-color: var(--bg-surface);">
            <h2 class="text-lg font-semibold mb-4" style="color: var(--text-primary);">Start New Run</h2>
            <form hx-post="/runs" hx-target="body">
                <label class="block text-sm mb-1" style="color: var(--text-secondary);">Requirements file path</label>
                <input type="text"
                       name="requirements_path"
                       placeholder="project_requirements.md (default)"
                       class="w-full p-2 rounded text-sm mb-4"
                       style="background-color: var(--bg-primary); border: 1px solid var(--border); color: var(--text-primary);">
                <div class="flex gap-3 justify-end">
                    <button type="button"
                            onclick="this.closest('.fixed').remove()"
                            class="px-4 py-2 rounded-lg text-sm"
                            style="color: var(--text-secondary); border: 1px solid var(--border);">
                        Cancel
                    </button>
                    <button type="submit"
                            class="px-4 py-2 rounded-lg text-sm font-medium"
                            style="background-color: var(--accent-purple); color: white;">
                        Start Pipeline
                    </button>
                </div>
            </form>
        </div>
    </div>
    '''
    return HTMLResponse(html)


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
