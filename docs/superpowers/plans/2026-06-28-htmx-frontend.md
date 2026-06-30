# QAura HTMX Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dark-themed HTMX web dashboard for the QAura pipeline with live SSE streaming, HITL approval, agent logs, and reports.

**Architecture:** A separate FastAPI app (`web/`) imports from `core.graph` and `core.state`. `PipelineManager` bridges the LangGraph pipeline to an `asyncio.Queue` that feeds an SSE endpoint. HTMX swaps partial HTML fragments into the page — no JS framework, no build step.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX 2.x (CDN), Tailwind CSS (CDN), sse-starlette, uvicorn

## Global Constraints

- Python >=3.12
- No new JS build tooling — HTMX and Tailwind from CDN only
- All web code lives under `web/` — never modify `core/` or `agents/` in this plan
- Dark theme using CSS custom properties defined in `web/static/styles.css`
- The CLI entry point (`python core/graph.py`) must remain functional
- Solo operator — no auth, no multi-tenancy
- One pipeline run at a time

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `web/__init__.py` | Package marker |
| Create | `web/app.py` | FastAPI app — routes, SSE endpoint, Jinja2 setup |
| Create | `web/pipeline.py` | `PipelineManager` — run lifecycle, event queue, HITL bridge |
| Create | `web/static/styles.css` | CSS custom properties, timeline connector, animations |
| Create | `web/templates/base.html` | Shared layout: sidebar, CDN imports, SSE extension |
| Create | `web/templates/dashboard.html` | Frame 1: live timeline + run summary |
| Create | `web/templates/agents.html` | Frame 2: tabbed agent logs |
| Create | `web/templates/reports.html` | Frame 3: KPIs, report, defects, healing |
| Create | `web/templates/partials/timeline/log_entry.html` | Single timeline event fragment |
| Create | `web/templates/partials/timeline/phase_badge.html` | Phase indicator fragment |
| Create | `web/templates/partials/timeline/approval_card.html` | HITL approval form fragment |
| Create | `web/templates/partials/summary/run_summary.html` | Run stats sidebar fragment |
| Create | `web/templates/partials/agents/agent_tab.html` | Per-agent log content fragment |
| Create | `web/templates/partials/reports/kpi_cards.html` | KPI stat cards fragment |
| Create | `web/templates/partials/reports/execution_table.html` | Execution results table fragment |
| Create | `web/templates/partials/reports/report_body.html` | QA report markdown fragment |
| Create | `web/templates/partials/reports/defect_card.html` | Defect analysis card fragment |
| Create | `web/templates/partials/reports/healing_entry.html` | Healing action entry fragment |
| Modify | `requirements.txt` | Add `uvicorn`, `jinja2`, `sse-starlette` |

---

### Task 1: Dependencies & Project Scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `web/__init__.py`
- Create: `web/static/styles.css`
- Create: `web/app.py` (minimal — just enough to serve a page)
- Create: `web/templates/base.html`
- Create: `web/templates/dashboard.html` (placeholder content)

**Interfaces:**
- Consumes: nothing
- Produces: A running FastAPI server at port 8000 serving a dark-themed shell page with sidebar nav

- [ ] **Step 1: Add dependencies to requirements.txt**

Append these three lines to the end of `requirements.txt`:

```
uvicorn>=0.30.0
jinja2>=3.1.0
sse-starlette>=2.0.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install uvicorn jinja2 sse-starlette`

- [ ] **Step 3: Create `web/__init__.py`**

```python
```

Empty file — just a package marker.

- [ ] **Step 4: Create `web/static/styles.css`**

```css
:root {
    --bg-primary: #0f1117;
    --bg-surface: #1a1d27;
    --bg-surface-hover: #242836;
    --border: #2a2e3a;
    --text-primary: #f0f0f0;
    --text-secondary: #8b8fa3;
    --accent-purple: #a78bfa;
    --accent-green: #4ade80;
    --accent-red: #f87171;
    --accent-yellow: #fbbf24;
    --accent-blue: #60a5fa;
    --accent-orange: #f97316;
    --accent-cyan: #06b6d4;
    --accent-pink: #e879f9;
}

body {
    background-color: var(--bg-primary);
    color: var(--text-primary);
}

/* Sidebar */
.sidebar {
    background-color: var(--bg-surface);
    border-right: 1px solid var(--border);
}

.nav-item.active {
    background-color: var(--bg-surface-hover);
    border-left: 3px solid var(--accent-purple);
}

/* Timeline */
.timeline {
    position: relative;
    padding-left: 2rem;
}

.timeline::before {
    content: '';
    position: absolute;
    left: 0.75rem;
    top: 0;
    bottom: 0;
    width: 2px;
    background-color: var(--border);
}

.timeline-dot {
    position: absolute;
    left: 0.5rem;
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 50%;
    margin-top: 0.375rem;
}

/* Status badges */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
}

.badge-completed { background-color: rgba(74, 222, 128, 0.15); color: var(--accent-green); }
.badge-running   { background-color: rgba(96, 165, 250, 0.15); color: var(--accent-blue); }
.badge-errored   { background-color: rgba(248, 113, 113, 0.15); color: var(--accent-red); }
.badge-idle      { background-color: rgba(139, 143, 163, 0.15); color: var(--text-secondary); }

/* Pulse animation for running badge */
@keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}
.badge-running::before {
    content: '';
    display: inline-block;
    width: 0.375rem;
    height: 0.375rem;
    border-radius: 50%;
    background-color: var(--accent-blue);
    margin-right: 0.375rem;
    animation: pulse-dot 1.5s ease-in-out infinite;
}

/* SSE fade-in for new entries */
@keyframes fade-in {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
.sse-new {
    animation: fade-in 0.3s ease-out;
}

/* Metadata pills */
.pill {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    background-color: var(--bg-surface-hover);
    color: var(--text-secondary);
    border: 1px solid var(--border);
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-secondary); }

/* KPI cards */
.kpi-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 1.25rem;
}

/* Cards */
.card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
}
```

- [ ] **Step 5: Create `web/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}QAura{% endblock %}</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"></script>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@3.4/dist/tailwind.min.css" rel="stylesheet">
    <link href="/static/styles.css" rel="stylesheet">
</head>
<body class="min-h-screen flex">
    <!-- Sidebar -->
    <aside class="sidebar w-56 flex-shrink-0 flex flex-col fixed h-full z-10">
        <div class="p-5 border-b" style="border-color: var(--border);">
            <div class="text-lg font-bold" style="color: var(--accent-purple);">QAura</div>
            <div class="text-xs mt-0.5" style="color: var(--text-secondary);">AGENTIC QA OPS</div>
        </div>
        <nav class="flex-1 py-4">
            <div class="px-4 pb-2 text-xs font-semibold uppercase tracking-wider" style="color: var(--text-secondary);">Operations</div>
            <a href="/dashboard"
               class="nav-item flex items-center gap-3 px-4 py-2.5 text-sm transition-colors {% if active_page == 'dashboard' %}active{% endif %}"
               style="color: var(--text-primary);">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                Pipeline Dashboard
            </a>
            <a href="/agents"
               class="nav-item flex items-center gap-3 px-4 py-2.5 text-sm transition-colors {% if active_page == 'agents' %}active{% endif %}"
               style="color: var(--text-primary);">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                Agent Logs
            </a>
            <a href="/reports"
               class="nav-item flex items-center gap-3 px-4 py-2.5 text-sm transition-colors {% if active_page == 'reports' %}active{% endif %}"
               style="color: var(--text-primary);">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                Reports & Analytics
            </a>
        </nav>
        <div class="p-4 border-t" style="border-color: var(--border);">
            <button hx-get="/partials/new-run-form"
                    hx-target="#modal-container"
                    hx-swap="innerHTML"
                    class="w-full py-2 px-4 rounded-lg text-sm font-medium transition-colors"
                    style="background-color: var(--accent-purple); color: white;">
                + New Run
            </button>
        </div>
    </aside>

    <!-- Main content -->
    <main class="flex-1 ml-56 min-h-screen">
        <div id="modal-container"></div>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 6: Create `web/templates/dashboard.html` (placeholder)**

```html
{% extends "base.html" %}
{% block title %}Pipeline Dashboard — QAura{% endblock %}

{% block content %}
<div class="p-8">
    <div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color: var(--text-secondary);">Operations</div>
    <h1 class="text-2xl font-bold mb-2" style="color: var(--accent-purple);">Pipeline Dashboard</h1>
    <p class="text-sm mb-8" style="color: var(--text-secondary);">Live pipeline execution — streamed from the orchestrator.</p>

    <div class="flex gap-6">
        <!-- Timeline column -->
        <div class="flex-1">
            <div id="timeline" class="timeline space-y-6">
                <p class="text-sm" style="color: var(--text-secondary);">No active run. Click <strong>+ New Run</strong> to start.</p>
            </div>
        </div>

        <!-- Run summary sidebar -->
        <div class="w-80 flex-shrink-0">
            <div id="run-summary" class="card p-5">
                <h3 class="font-semibold mb-3">Run summary</h3>
                <p class="text-sm" style="color: var(--text-secondary);">Waiting for a run to start.</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Create minimal `web/app.py`**

```python
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="QAura Dashboard")

app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


@app.get("/")
async def index():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
    })


@app.get("/agents")
async def agents_page(request: Request):
    return templates.TemplateResponse("agents.html", {
        "request": request,
        "active_page": "agents",
    })


@app.get("/reports")
async def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {
        "request": request,
        "active_page": "reports",
    })
```

- [ ] **Step 8: Verify the server starts and renders**

Run: `cd F:\Career\Projects\QAura && python -m uvicorn web.app:app --port 8000`

Open browser to `http://localhost:8000`. Expected: dark-themed page with sidebar (QAura logo, 3 nav links, New Run button) and a "No active run" placeholder in the main area.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt web/__init__.py web/app.py web/static/styles.css web/templates/base.html web/templates/dashboard.html
git commit -m "feat(web): scaffold FastAPI + Jinja2 + HTMX dark-themed shell"
```

---

### Task 2: PipelineManager & SSE Streaming

**Files:**
- Create: `web/pipeline.py`
- Modify: `web/app.py` — add SSE endpoint and `POST /runs`

**Interfaces:**
- Consumes: `core.graph.graph` (compiled LangGraph), `core.graph.get_initial_state(path) -> dict`, `core.graph.graph.astream(state, config, stream_mode, subgraphs)`, `core.graph.graph.get_state(config)`, `langgraph.types.Command`
- Produces: `PipelineManager` class with methods: `start_run(requirements_path: str) -> str` (returns run_id), `get_event_stream(run_id: str) -> AsyncGenerator[dict, None]`, `get_run_state(run_id: str) -> dict | None`, `approve_run(run_id: str, approved: bool, feedback: str) -> None`, `is_running -> bool`

- [ ] **Step 1: Create `web/pipeline.py`**

```python
import asyncio
import time
from datetime import datetime, timezone

from langgraph.types import Command

from core.graph import graph, get_initial_state


class PipelineEvent:
    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data


class PipelineManager:
    def __init__(self):
        self._run_id: str | None = None
        self._config: dict | None = None
        self._queue: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        self._approval_event: asyncio.Event = asyncio.Event()
        self._approval_data: dict = {}
        self._running: bool = False
        self._phase: str = "idle"
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_run_id(self) -> str | None:
        return self._run_id

    @property
    def current_phase(self) -> str:
        return self._phase

    def start_run(self, requirements_path: str) -> str:
        if self._running:
            raise RuntimeError("A pipeline run is already in progress")

        run_id = f"qaura_run_{int(time.time())}"
        self._run_id = run_id
        self._config = {"configurable": {"thread_id": run_id}}
        self._queue = asyncio.Queue()
        self._approval_event = asyncio.Event()
        self._approval_data = {}
        self._running = True
        self._phase = "initializing"

        initial_state = get_initial_state(requirements_path)
        self._task = asyncio.create_task(self._run(initial_state))
        return run_id

    async def _run(self, initial_state: dict):
        try:
            self._push("phase_change", {"phase": "Phase 1: Planning", "agent_name": "test_architect", "status": "running"})

            async for event in graph.astream(
                initial_state, config=self._config, stream_mode="updates", subgraphs=True,
            ):
                self._process_stream_event(event)

            state = graph.get_state(self._config)
            state_values = state.values

            if state_values.get("test_plan") and state.next:
                self._phase = "awaiting_approval"
                plan = state_values["test_plan"]
                plan_data = plan.model_dump() if hasattr(plan, "model_dump") else plan
                self._push("plan_ready", {"plan": plan_data})

                self._approval_event.clear()
                await self._approval_event.wait()

                approved = self._approval_data.get("approved", False)
                feedback = self._approval_data.get("feedback", "")

                if approved:
                    self._push("phase_change", {"phase": "Phase 2: Generation", "agent_name": "unit_test_gen", "status": "running"})
                else:
                    self._push("agent_log", {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "agent": "human_approval",
                        "message": "Plan rejected by operator.",
                        "tool_calls": [],
                    })

                async for event in graph.astream(
                    Command(resume={"approved": approved, "feedback": feedback}),
                    config=self._config,
                    stream_mode="updates",
                    subgraphs=True,
                ):
                    self._process_stream_event(event)

            final_state = graph.get_state(self._config).values
            self._phase = "complete"
            self._push("run_complete", {
                "execution_summary": self._serialize(final_state.get("execution_summary")),
                "qa_report": self._serialize(final_state.get("qa_report")),
            })
        except Exception as e:
            self._phase = "errored"
            self._push("agent_log", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": "system",
                "message": f"Pipeline error: {e}",
                "tool_calls": [],
            })
            self._push("run_complete", {})
        finally:
            self._running = False
            await self._queue.put(None)

    def _process_stream_event(self, event):
        namespace, update = event
        ts = datetime.now(timezone.utc).isoformat()

        if namespace:
            agent_name = namespace[0]
            for node_name, node_update in update.items():
                if node_name == "agent":
                    messages = node_update.get("messages", [])
                    if messages:
                        last_msg = messages[-1]
                        tool_calls = []
                        message_text = "Agent provided a response."
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            tool_calls = [{"name": tc["name"]} for tc in last_msg.tool_calls]
                            message_text = f"Calling tools: {[tc['name'] for tc in tool_calls]}"
                        self._push("agent_log", {
                            "timestamp": ts,
                            "agent": agent_name,
                            "message": message_text,
                            "tool_calls": tool_calls,
                        })
                elif node_name == "tools":
                    self._push("agent_log", {
                        "timestamp": ts,
                        "agent": agent_name,
                        "message": "Tool execution finished.",
                        "tool_calls": [],
                    })
        else:
            for node_name in update.keys():
                if node_name == "__metadata__":
                    continue
                phase_map = {
                    "test_architect": "Phase 1: Planning",
                    "human_approval": "Phase 1: Approval",
                    "unit_test_gen": "Phase 2: Unit Tests",
                    "e2e_gen": "Phase 2: E2E Tests",
                    "execution_agent": "Phase 3: Execution",
                    "reporting_agent": "Phase 4: Reporting",
                    "defect_intelligence_agent": "Phase 4: Defect Analysis",
                    "self_healing_agent": "Phase 5: Self-Healing",
                }
                self._phase = phase_map.get(node_name, node_name)
                self._push("phase_change", {
                    "phase": self._phase,
                    "agent_name": node_name,
                    "status": "completed",
                })

    def _push(self, event_type: str, data: dict):
        self._queue.put_nowait(PipelineEvent(event_type, data))

    def _serialize(self, obj):
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return obj

    async def get_event_stream(self, run_id: str):
        if run_id != self._run_id:
            return
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    def get_run_state(self, run_id: str) -> dict | None:
        if run_id != self._run_id or self._config is None:
            return None
        try:
            return graph.get_state(self._config).values
        except Exception:
            return None

    def approve_run(self, run_id: str, approved: bool, feedback: str = ""):
        if run_id != self._run_id:
            raise ValueError(f"No active run with id {run_id}")
        self._approval_data = {"approved": approved, "feedback": feedback}
        self._approval_event.set()


pipeline_manager = PipelineManager()
```

- [ ] **Step 2: Add SSE endpoint and POST /runs to `web/app.py`**

Add these imports to the top of `web/app.py`:

```python
import json
from fastapi import Form
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from web.pipeline import pipeline_manager
```

Add these routes after the existing page routes:

```python
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
```

- [ ] **Step 3: Verify SSE endpoint works**

Run: `python -m uvicorn web.app:app --port 8000 --reload`

Open `http://localhost:8000` — the dashboard should render. The SSE endpoint exists at `/sse/pipeline/{run_id}` but won't stream until a run starts (tested in Task 3).

- [ ] **Step 4: Commit**

```bash
git add web/pipeline.py web/app.py
git commit -m "feat(web): add PipelineManager with SSE streaming and run/approve routes"
```

---

### Task 3: Dashboard Live Timeline & SSE Integration

**Files:**
- Modify: `web/templates/dashboard.html` — add SSE connection, timeline structure
- Create: `web/templates/partials/timeline/log_entry.html`
- Create: `web/templates/partials/timeline/phase_badge.html`
- Create: `web/templates/partials/summary/run_summary.html`
- Modify: `web/app.py` — add partial render routes for SSE

**Interfaces:**
- Consumes: `pipeline_manager.is_running`, `pipeline_manager.current_run_id`, `pipeline_manager.current_phase`. SSE events: `agent_log` (fields: `timestamp`, `agent`, `message`, `tool_calls`), `phase_change` (fields: `phase`, `agent_name`, `status`), `stats_update`, `run_complete`
- Produces: Live-updating dashboard page that renders streamed events into the timeline

- [ ] **Step 1: Create partial directories**

```bash
mkdir -p web/templates/partials/timeline web/templates/partials/summary web/templates/partials/agents web/templates/partials/reports
```

- [ ] **Step 2: Create `web/templates/partials/timeline/log_entry.html`**

```html
<div class="relative sse-new" style="padding-left: 1.5rem;">
    <div class="timeline-dot" style="background-color: {{ agent_color }};"></div>
    <div class="flex items-center gap-2 mb-1">
        <span class="text-xs" style="color: var(--text-secondary);">{{ timestamp_short }}</span>
        <span class="text-xs font-medium" style="color: {{ agent_color }};">{{ agent_display }}</span>
        <span class="badge badge-{{ status }}">{{ status }}</span>
    </div>
    <p class="text-sm" style="color: var(--text-primary);">{{ message }}</p>
    {% if pills %}
    <div class="flex gap-2 mt-1.5">
        {% for pill in pills %}
        <span class="pill">{{ pill }}</span>
        {% endfor %}
    </div>
    {% endif %}
</div>
```

- [ ] **Step 3: Create `web/templates/partials/timeline/phase_badge.html`**

```html
<div class="flex items-center gap-2 px-4 py-2 rounded-lg" style="background-color: var(--bg-surface); border: 1px solid var(--border);">
    <span class="badge badge-{{ status }}">{{ status }}</span>
    <span class="text-sm font-medium" style="color: var(--text-primary);">{{ phase }}</span>
</div>
```

- [ ] **Step 4: Create `web/templates/partials/summary/run_summary.html`**

```html
<div class="space-y-4">
    <div>
        <h3 class="font-semibold mb-3" style="color: var(--text-primary);">Run summary</h3>
        {% if run_id %}
        <p class="text-xs mb-3" style="color: var(--text-secondary);">{{ run_id }}</p>
        {% endif %}
    </div>

    <div class="space-y-2">
        <div class="flex justify-between text-sm">
            <span style="color: var(--text-secondary);">PHASE</span>
            <span style="color: var(--text-primary);">{{ phase }}</span>
        </div>
        {% if stats %}
        <div class="flex justify-between text-sm">
            <span style="color: var(--text-secondary);">TESTS RUN</span>
            <span style="color: var(--text-primary);">{{ stats.total_tests }}</span>
        </div>
        <div class="flex justify-between text-sm">
            <span style="color: var(--text-secondary);">PASSED</span>
            <span style="color: var(--accent-green);">{{ stats.passed }}</span>
        </div>
        <div class="flex justify-between text-sm">
            <span style="color: var(--text-secondary);">FAILED</span>
            <span style="color: var(--accent-red);">{{ stats.failed }}</span>
        </div>
        <div class="flex justify-between text-sm">
            <span style="color: var(--text-secondary);">BLOCKED</span>
            <span style="color: var(--accent-yellow);">{{ stats.blocked }}</span>
        </div>
        {% endif %}
    </div>

    {% if agent_events %}
    <div class="pt-3 border-t" style="border-color: var(--border);">
        <h4 class="text-xs font-semibold uppercase mb-2" style="color: var(--text-secondary);">Agent participation</h4>
        {% for agent_name, count in agent_events.items() %}
        <div class="flex items-center gap-2 mb-1.5">
            <span class="text-xs w-28 truncate" style="color: var(--text-primary);">{{ agent_name }}</span>
            <div class="flex-1 h-1.5 rounded-full" style="background-color: var(--bg-surface-hover);">
                <div class="h-1.5 rounded-full" style="background-color: {{ agent_colors[agent_name] }}; width: {{ (count / max_events * 100) | int }}%;"></div>
            </div>
            <span class="text-xs w-4 text-right" style="color: var(--text-secondary);">{{ count }}</span>
        </div>
        {% endfor %}
    </div>
    {% endif %}
</div>
```

- [ ] **Step 5: Update `web/templates/dashboard.html` with SSE connection**

Replace the entire content of `web/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Pipeline Dashboard — QAura{% endblock %}

{% block content %}
<div class="p-8">
    <div class="flex items-center justify-between mb-6">
        <div>
            <div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color: var(--text-secondary);">
                {% if run_id %}LIVE &middot; PIPELINE {{ run_id }}{% else %}Operations{% endif %}
            </div>
            <h1 class="text-2xl font-bold" style="color: var(--accent-purple);">Pipeline Dashboard</h1>
            <p class="text-sm mt-1" style="color: var(--text-secondary);">Live pipeline execution — streamed from the orchestrator.</p>
        </div>
        <div id="phase-badge">
            {% if run_id %}
            <div class="flex items-center gap-2 px-4 py-2 rounded-lg" style="background-color: var(--bg-surface); border: 1px solid var(--border);">
                <span class="badge badge-running">running</span>
                <span class="text-sm font-medium">Initializing</span>
            </div>
            {% endif %}
        </div>
    </div>

    <div class="flex gap-6">
        <!-- Timeline column -->
        <div class="flex-1">
            <div id="timeline" class="timeline space-y-6">
                {% if not run_id %}
                <p class="text-sm" style="color: var(--text-secondary);">No active run. Click <strong>+ New Run</strong> to start.</p>
                {% endif %}
            </div>
        </div>

        <!-- Run summary sidebar -->
        <div class="w-80 flex-shrink-0">
            <div id="run-summary" class="card p-5">
                {% if run_id %}
                {% include "partials/summary/run_summary.html" %}
                {% else %}
                <h3 class="font-semibold mb-3">Run summary</h3>
                <p class="text-sm" style="color: var(--text-secondary);">Waiting for a run to start.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>

{% if run_id %}
<!-- SSE connection — agent_log events append to timeline -->
<div hx-ext="sse"
     sse-connect="/sse/pipeline/{{ run_id }}"
     sse-swap="agent_log"
     hx-target="#timeline"
     hx-swap="beforeend">

    <!-- phase_change events swap the phase badge -->
    <div sse-swap="phase_change"
         hx-target="#phase-badge"
         hx-swap="innerHTML"></div>

    <!-- stats_update events swap the run summary -->
    <div sse-swap="stats_update"
         hx-target="#run-summary"
         hx-swap="innerHTML"></div>

    <!-- plan_ready events append approval card to timeline -->
    <div sse-swap="plan_ready"
         hx-target="#timeline"
         hx-swap="beforeend"></div>

    <!-- run_complete event -->
    <div sse-swap="run_complete"
         hx-target="#phase-badge"
         hx-swap="innerHTML"></div>
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Add SSE partial rendering to `web/app.py`**

The SSE endpoint currently sends raw JSON. For HTMX's `sse-swap` to work, each event needs to send rendered HTML. Modify the `sse_pipeline` endpoint and add a helper:

```python
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
```

Then replace the `sse_pipeline` endpoint:

```python
@app.get("/sse/pipeline/{run_id}")
async def sse_pipeline(run_id: str, request: Request):
    async def event_generator():
        async for event in pipeline_manager.get_event_stream(run_id):
            yield _render_sse_event(event, templates)

    return EventSourceResponse(event_generator())
```

- [ ] **Step 7: Update dashboard route to pass run_id**

Replace the `dashboard` route:

```python
@app.get("/dashboard")
async def dashboard(request: Request):
    run_id = request.query_params.get("run_id") or pipeline_manager.current_run_id
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "run_id": run_id if pipeline_manager.is_running else None,
        "phase": pipeline_manager.current_phase,
    })
```

- [ ] **Step 8: Verify end-to-end SSE streaming**

Run the server: `python -m uvicorn web.app:app --port 8000 --reload`

In a separate terminal, start the demo app: `cd demo_app && python -m uvicorn server:app --port 3000`

Open `http://localhost:8000/dashboard`. Click "+ New Run" (the form doesn't exist yet — for now test via curl):

```bash
curl -X POST http://localhost:8000/runs -d "requirements_path=" -L
```

Expected: the pipeline starts, the dashboard at `/dashboard?run_id=qaura_run_...` shows SSE events streaming in as rendered HTML fragments.

- [ ] **Step 9: Commit**

```bash
git add web/templates/dashboard.html web/templates/partials/timeline/ web/templates/partials/summary/ web/app.py
git commit -m "feat(web): live dashboard with SSE timeline and phase badge streaming"
```

---

### Task 4: HITL Approval Card & New Run Form

**Files:**
- Create: `web/templates/partials/timeline/approval_card.html`
- Modify: `web/app.py` — add new-run form partial route
- Modify: `web/templates/base.html` — ensure modal container works

**Interfaces:**
- Consumes: SSE `plan_ready` event with `plan` dict (fields: `project_summary`, `components` list of `{name, file_path, testing_type, risk_level, description}`, `unit_scope`, `integration_scope`, `e2e_scope`, `risk_areas`). `POST /runs/{run_id}/approve` accepting form with `approved` and `feedback` fields.
- Produces: Inline approval card rendered in the timeline. New Run form modal.

- [ ] **Step 1: Create `web/templates/partials/timeline/approval_card.html`**

```html
<div id="approval-card" class="sse-new card p-5 my-4" style="border-color: var(--accent-purple); border-width: 2px;">
    <div class="flex items-center gap-2 mb-4">
        <span class="badge badge-running">awaiting approval</span>
        <span class="text-sm font-medium" style="color: var(--text-primary);">Test Plan Review</span>
    </div>

    {% if plan.project_summary %}
    <p class="text-sm mb-4" style="color: var(--text-secondary);">{{ plan.project_summary }}</p>
    {% endif %}

    <!-- Component table -->
    <div class="mb-4 overflow-x-auto">
        <table class="w-full text-sm">
            <thead>
                <tr style="color: var(--text-secondary); border-bottom: 1px solid var(--border);">
                    <th class="text-left py-2 font-medium">Component</th>
                    <th class="text-left py-2 font-medium">File</th>
                    <th class="text-left py-2 font-medium">Type</th>
                    <th class="text-left py-2 font-medium">Risk</th>
                </tr>
            </thead>
            <tbody>
                {% for comp in plan.get("components", []) %}
                <tr style="border-bottom: 1px solid var(--border);">
                    <td class="py-2" style="color: var(--text-primary);">{{ comp.name }}</td>
                    <td class="py-2" style="color: var(--text-secondary);">{{ comp.file_path }}</td>
                    <td class="py-2">
                        <span class="pill">{{ comp.testing_type }}</span>
                    </td>
                    <td class="py-2">
                        {% if comp.risk_level == "High" %}
                        <span class="pill" style="color: var(--accent-red); border-color: var(--accent-red);">High</span>
                        {% elif comp.risk_level == "Medium" %}
                        <span class="pill" style="color: var(--accent-yellow); border-color: var(--accent-yellow);">Medium</span>
                        {% else %}
                        <span class="pill" style="color: var(--accent-green); border-color: var(--accent-green);">Low</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <!-- Scopes -->
    <div class="grid grid-cols-3 gap-3 mb-4 text-xs">
        <div class="p-2 rounded" style="background-color: var(--bg-surface-hover);">
            <div class="font-semibold mb-1" style="color: var(--text-secondary);">Unit Scope</div>
            {% for s in plan.get("unit_scope", []) %}
            <div style="color: var(--text-primary);">{{ s }}</div>
            {% endfor %}
        </div>
        <div class="p-2 rounded" style="background-color: var(--bg-surface-hover);">
            <div class="font-semibold mb-1" style="color: var(--text-secondary);">Integration Scope</div>
            {% for s in plan.get("integration_scope", []) %}
            <div style="color: var(--text-primary);">{{ s }}</div>
            {% endfor %}
        </div>
        <div class="p-2 rounded" style="background-color: var(--bg-surface-hover);">
            <div class="font-semibold mb-1" style="color: var(--text-secondary);">E2E Scope</div>
            {% for s in plan.get("e2e_scope", []) %}
            <div style="color: var(--text-primary);">{{ s }}</div>
            {% endfor %}
        </div>
    </div>

    <!-- Risk areas -->
    {% if plan.get("risk_areas") %}
    <div class="mb-4">
        <div class="text-xs font-semibold mb-1" style="color: var(--text-secondary);">Risk Areas</div>
        {% for risk in plan.risk_areas %}
        <div class="text-sm" style="color: var(--accent-yellow);">- {{ risk }}</div>
        {% endfor %}
    </div>
    {% endif %}

    <!-- Approval form -->
    <form class="space-y-3">
        <textarea name="feedback"
                  placeholder="Optional feedback..."
                  rows="2"
                  class="w-full p-2 rounded text-sm"
                  style="background-color: var(--bg-primary); border: 1px solid var(--border); color: var(--text-primary); resize: vertical;"></textarea>
        <div class="flex gap-3">
            <button hx-post="/runs/{{ run_id }}/approve"
                    hx-vals='{"approved": "true"}'
                    hx-include="[name='feedback']"
                    hx-target="#approval-card"
                    hx-swap="outerHTML"
                    class="px-4 py-2 rounded-lg text-sm font-medium"
                    style="background-color: var(--accent-green); color: #0f1117;">
                Approve
            </button>
            <button hx-post="/runs/{{ run_id }}/approve"
                    hx-vals='{"approved": "false"}'
                    hx-include="[name='feedback']"
                    hx-target="#approval-card"
                    hx-swap="outerHTML"
                    class="px-4 py-2 rounded-lg text-sm font-medium"
                    style="background-color: var(--accent-red); color: #0f1117;">
                Reject
            </button>
        </div>
    </form>
</div>
```

- [ ] **Step 2: Add new-run form partial route to `web/app.py`**

```python
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
```

- [ ] **Step 3: Verify HITL approval flow end-to-end**

1. Start demo app and QAura dashboard
2. Click "+ New Run" → modal appears → click "Start Pipeline"
3. Dashboard shows SSE events streaming in
4. When plan_ready fires, the approval card appears inline with the component table
5. Click "Approve" → card replaced with "approved" badge → pipeline resumes

- [ ] **Step 4: Commit**

```bash
git add web/templates/partials/timeline/approval_card.html web/app.py
git commit -m "feat(web): HITL approval card and new-run form modal"
```

---

### Task 5: Agent Logs Page (Frame 2)

**Files:**
- Create: `web/templates/agents.html` (full page)
- Create: `web/templates/partials/agents/agent_tab.html`
- Modify: `web/app.py` — add agent log partial route
- Modify: `web/pipeline.py` — track per-agent event logs

**Interfaces:**
- Consumes: `pipeline_manager.get_agent_logs(agent_name: str) -> list[dict]` (new method), SSE `agent_log` events for live updates
- Produces: Tabbed agent log page at `/agents`, tab content loads via `GET /partials/agents/{agent_name}/logs`

- [ ] **Step 1: Add per-agent log tracking to `web/pipeline.py`**

Add this field to `PipelineManager.__init__`:

```python
self._agent_logs: dict[str, list[dict]] = {}
```

Add this method to `PipelineManager`:

```python
def get_agent_logs(self, agent_name: str) -> list[dict]:
    return self._agent_logs.get(agent_name, [])

def get_all_agent_names(self) -> list[str]:
    return list(self._agent_logs.keys())
```

In `_process_stream_event`, after every `self._push("agent_log", ...)` call, also append to the per-agent log:

```python
agent = data.get("agent") if etype == "agent_log" else agent_name
if agent not in self._agent_logs:
    self._agent_logs[agent] = []
self._agent_logs[agent].append(data)
```

Specifically, in the section where `node_name == "agent"`, after the `self._push("agent_log", {...})` line, add:

```python
if agent_name not in self._agent_logs:
    self._agent_logs[agent_name] = []
self._agent_logs[agent_name].append({
    "timestamp": ts,
    "agent": agent_name,
    "message": message_text,
    "tool_calls": tool_calls,
})
```

And in the `node_name == "tools"` section, after the push:

```python
if agent_name not in self._agent_logs:
    self._agent_logs[agent_name] = []
self._agent_logs[agent_name].append({
    "timestamp": ts,
    "agent": agent_name,
    "message": "Tool execution finished.",
    "tool_calls": [],
})
```

Also reset `self._agent_logs = {}` in `start_run()`.

- [ ] **Step 2: Create `web/templates/agents.html`**

```html
{% extends "base.html" %}
{% block title %}Agent Logs — QAura{% endblock %}

{% block content %}
<div class="p-8">
    <div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color: var(--text-secondary);">Operations</div>
    <h1 class="text-2xl font-bold mb-2" style="color: var(--accent-purple);">Agent Logs</h1>
    <p class="text-sm mb-6" style="color: var(--text-secondary);">Per-agent tool calls, reasoning, and structured output.</p>

    <!-- Agent tabs -->
    <div class="flex gap-1 mb-6 border-b" style="border-color: var(--border);">
        {% for agent_key, agent_info in agents.items() %}
        <button class="px-4 py-2 text-sm transition-colors rounded-t"
                hx-get="/partials/agents/{{ agent_key }}/logs"
                hx-target="#agent-log-content"
                hx-swap="innerHTML"
                style="color: {{ agent_info.color }}; {% if loop.first %}background-color: var(--bg-surface); border: 1px solid var(--border); border-bottom: none;{% endif %}"
                onclick="document.querySelectorAll('[data-agent-tab]').forEach(t => { t.style.backgroundColor = ''; t.style.border = ''; }); this.style.backgroundColor = 'var(--bg-surface)'; this.style.border = '1px solid var(--border)'; this.style.borderBottom = 'none';"
                data-agent-tab>
            {{ agent_info.display }}
        </button>
        {% endfor %}
    </div>

    <!-- Tab content -->
    <div id="agent-log-content" class="card p-5">
        {% if first_agent %}
        {% include "partials/agents/agent_tab.html" %}
        {% else %}
        <p class="text-sm" style="color: var(--text-secondary);">No agent activity yet. Start a pipeline run to see logs.</p>
        {% endif %}
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Create `web/templates/partials/agents/agent_tab.html`**

```html
<div>
    <div class="flex items-center gap-3 mb-4">
        <span class="text-sm font-medium" style="color: {{ agent_color }};">{{ agent_display }}</span>
        <span class="badge badge-{{ agent_status }}">{{ agent_status }}</span>
        <span class="text-xs" style="color: var(--text-secondary);">{{ logs | length }} events</span>
    </div>

    {% if logs %}
    <div class="space-y-3">
        {% for log in logs %}
        <div class="p-3 rounded" style="background-color: var(--bg-primary); border: 1px solid var(--border);">
            <div class="flex items-center gap-2 mb-1">
                <span class="text-xs" style="color: var(--text-secondary);">{{ log.timestamp[11:19] if log.timestamp|length > 19 else log.timestamp }}</span>
                {% if log.tool_calls %}
                <span class="pill">tools: {{ log.tool_calls | length }}</span>
                {% endif %}
            </div>
            <p class="text-sm" style="color: var(--text-primary);">{{ log.message }}</p>
            {% if log.tool_calls %}
            <div class="mt-2 space-y-1">
                {% for tc in log.tool_calls %}
                <div class="text-xs font-mono px-2 py-1 rounded" style="background-color: var(--bg-surface-hover); color: var(--accent-cyan);">{{ tc.name }}</div>
                {% endfor %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <p class="text-sm" style="color: var(--text-secondary);">No activity recorded for this agent yet.</p>
    {% endif %}
</div>
```

- [ ] **Step 4: Add routes to `web/app.py`**

Update the `agents_page` route and add the partial:

```python
@app.get("/agents")
async def agents_page(request: Request):
    agents = {
        "test_architect": {"display": "Test Architect", "color": AGENT_COLORS["test_architect"]},
        "unit_test_gen": {"display": "Unit Generator", "color": AGENT_COLORS["unit_test_gen"]},
        "e2e_gen": {"display": "E2E Generator", "color": AGENT_COLORS["e2e_gen"]},
        "execution_agent": {"display": "Execution Runner", "color": AGENT_COLORS["execution_agent"]},
        "reporting_agent": {"display": "Reporting", "color": AGENT_COLORS["reporting_agent"]},
        "defect_intelligence_agent": {"display": "Defect Intelligence", "color": AGENT_COLORS["defect_intelligence_agent"]},
        "self_healing_agent": {"display": "Self-Healing", "color": AGENT_COLORS["self_healing_agent"]},
    }

    first_agent_key = next(iter(agents))
    first_agent_logs = pipeline_manager.get_agent_logs(first_agent_key)

    return templates.TemplateResponse("agents.html", {
        "request": request,
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

    if pipeline_manager.is_running and pipeline_manager.current_phase and agent_name in pipeline_manager.current_phase.lower().replace(" ", "_"):
        status = "running"

    html = templates.get_template("partials/agents/agent_tab.html").render(
        agent_display=display,
        agent_color=color,
        agent_status=status,
        logs=logs,
    )
    return HTMLResponse(html)
```

- [ ] **Step 5: Verify agent logs page**

Navigate to `http://localhost:8000/agents`. Expected: tabbed interface with all 7 agents. Click tabs to switch between agents. After running a pipeline, logs should appear under each agent's tab.

- [ ] **Step 6: Commit**

```bash
git add web/pipeline.py web/templates/agents.html web/templates/partials/agents/agent_tab.html web/app.py
git commit -m "feat(web): agent logs page with tabbed per-agent view"
```

---

### Task 6: Reports & Analytics Page (Frame 3)

**Files:**
- Create: `web/templates/reports.html`
- Create: `web/templates/partials/reports/kpi_cards.html`
- Create: `web/templates/partials/reports/execution_table.html`
- Create: `web/templates/partials/reports/report_body.html`
- Create: `web/templates/partials/reports/defect_card.html`
- Create: `web/templates/partials/reports/healing_entry.html`
- Modify: `web/app.py` — update reports route with state data

**Interfaces:**
- Consumes: `pipeline_manager.get_run_state(run_id) -> dict` which returns `QAuraState` fields: `execution_summary` (`ExecutionResultsSummary` with `total_tests`, `passed`, `failed`, `blocked`, `critical_path_success`), `coverage_assessment` (`CoverageConfidenceAssessment` with `overall_confidence`, `component_scores`), `anomaly_reports` (list of `StructuredAnomalyReport` with `anomaly_id`, `affected_component`, `classification`, `root_cause_hypothesis`), `qa_report` (`QAReport` with `sections`, `overall_verdict`, `executive_summary`), `defect_analyses` (list of `DefectAnalysis`), `healing_actions` (list of `HealingAction`)
- Produces: Reports & Analytics page at `/reports` with KPI cards, execution table, rendered QA report, defect cards, healing entries

- [ ] **Step 1: Create `web/templates/partials/reports/kpi_cards.html`**

```html
<div class="grid grid-cols-4 gap-4 mb-6">
    <div class="kpi-card">
        <div class="text-xs font-semibold uppercase" style="color: var(--text-secondary);">Pass Rate</div>
        <div class="text-3xl font-bold mt-1" style="color: var(--text-primary);">
            {% if stats and stats.total_tests > 0 %}
            {{ "%.1f" | format(stats.passed / stats.total_tests * 100) }}%
            {% else %}—{% endif %}
        </div>
    </div>
    <div class="kpi-card">
        <div class="text-xs font-semibold uppercase" style="color: var(--text-secondary);">Coverage</div>
        <div class="text-3xl font-bold mt-1" style="color: var(--text-primary);">
            {% if coverage %}
            {{ "%.0f" | format(coverage.overall_confidence * 100) }}%
            {% else %}—{% endif %}
        </div>
    </div>
    <div class="kpi-card">
        <div class="text-xs font-semibold uppercase" style="color: var(--text-secondary);">Anomalies</div>
        <div class="text-3xl font-bold mt-1" style="color: {% if anomaly_count > 0 %}var(--accent-red){% else %}var(--text-primary){% endif %};">
            {{ anomaly_count }}
        </div>
    </div>
    <div class="kpi-card">
        <div class="text-xs font-semibold uppercase" style="color: var(--text-secondary);">Healing Rate</div>
        <div class="text-3xl font-bold mt-1" style="color: var(--text-primary);">
            {% if healing_total > 0 %}
            {{ "%.0f" | format(healing_success / healing_total * 100) }}%
            {% else %}—{% endif %}
        </div>
    </div>
</div>
```

- [ ] **Step 2: Create `web/templates/partials/reports/execution_table.html`**

```html
<div class="card p-5 mb-6">
    <h3 class="font-semibold mb-3" style="color: var(--text-primary);">Execution Summary</h3>
    {% if stats %}
    <div class="grid grid-cols-4 gap-4 mb-4 text-center">
        <div>
            <div class="text-2xl font-bold" style="color: var(--text-primary);">{{ stats.total_tests }}</div>
            <div class="text-xs" style="color: var(--text-secondary);">Total</div>
        </div>
        <div>
            <div class="text-2xl font-bold" style="color: var(--accent-green);">{{ stats.passed }}</div>
            <div class="text-xs" style="color: var(--text-secondary);">Passed</div>
        </div>
        <div>
            <div class="text-2xl font-bold" style="color: var(--accent-red);">{{ stats.failed }}</div>
            <div class="text-xs" style="color: var(--text-secondary);">Failed</div>
        </div>
        <div>
            <div class="text-2xl font-bold" style="color: var(--accent-yellow);">{{ stats.blocked }}</div>
            <div class="text-xs" style="color: var(--text-secondary);">Blocked</div>
        </div>
    </div>
    <div class="flex items-center gap-2 text-sm">
        <span style="color: var(--text-secondary);">Critical Path:</span>
        {% if stats.critical_path_success %}
        <span class="badge badge-completed">passing</span>
        {% else %}
        <span class="badge badge-errored">failing</span>
        {% endif %}
    </div>
    {% if coverage and coverage.component_scores %}
    <div class="mt-4 border-t pt-4" style="border-color: var(--border);">
        <h4 class="text-xs font-semibold uppercase mb-2" style="color: var(--text-secondary);">Per-Component Scores</h4>
        {% for cs in coverage.component_scores %}
        <div class="flex items-center gap-2 mb-1.5">
            <span class="text-xs w-32 truncate" style="color: var(--text-primary);">{{ cs.component }}</span>
            <div class="flex-1 h-1.5 rounded-full" style="background-color: var(--bg-surface-hover);">
                <div class="h-1.5 rounded-full" style="background-color: {% if cs.score >= 0.8 %}var(--accent-green){% elif cs.score >= 0.5 %}var(--accent-yellow){% else %}var(--accent-red){% endif %}; width: {{ (cs.score * 100) | int }}%;"></div>
            </div>
            <span class="text-xs w-10 text-right" style="color: var(--text-secondary);">{{ "%.0f" | format(cs.score * 100) }}%</span>
        </div>
        {% endfor %}
    </div>
    {% endif %}
    {% else %}
    <p class="text-sm" style="color: var(--text-secondary);">No execution data yet.</p>
    {% endif %}
</div>
```

- [ ] **Step 3: Create `web/templates/partials/reports/report_body.html`**

```html
<div class="card p-5 mb-6">
    <div class="flex items-center justify-between mb-4">
        <h3 class="font-semibold" style="color: var(--text-primary);">QA Report</h3>
        {% if report %}
        <span class="badge {% if report.overall_verdict == 'PASS' %}badge-completed{% elif report.overall_verdict == 'FAIL' %}badge-errored{% else %}badge-running{% endif %}">
            {{ report.overall_verdict }}
        </span>
        {% endif %}
    </div>
    {% if report %}
    <p class="text-sm mb-4" style="color: var(--text-secondary);">{{ report.executive_summary }}</p>
    {% for section in report.sections %}
    <div class="mb-4">
        <h4 class="text-sm font-semibold mb-1" style="color: var(--text-primary);">{{ section.title }}</h4>
        <div class="text-sm" style="color: var(--text-secondary); white-space: pre-wrap;">{{ section.content }}</div>
    </div>
    {% endfor %}
    {% else %}
    <p class="text-sm" style="color: var(--text-secondary);">No report generated yet.</p>
    {% endif %}
</div>
```

- [ ] **Step 4: Create `web/templates/partials/reports/defect_card.html`**

```html
<div class="card p-4 mb-3" style="border-left: 3px solid {% if analysis.classification == 'APPLICATION_DEFECT' %}var(--accent-red){% elif analysis.classification == 'INFRASTRUCTURE' %}var(--accent-yellow){% else %}var(--accent-blue){% endif %};">
    <div class="flex items-center gap-2 mb-2">
        <span class="text-sm font-mono font-bold" style="color: var(--text-primary);">{{ analysis.anomaly_id }}</span>
        <span class="pill" style="{% if analysis.classification == 'APPLICATION_DEFECT' %}color: var(--accent-red); border-color: var(--accent-red);{% elif analysis.classification == 'INFRASTRUCTURE' %}color: var(--accent-yellow); border-color: var(--accent-yellow);{% else %}color: var(--accent-blue); border-color: var(--accent-blue);{% endif %}">
            {{ analysis.classification }}
        </span>
        <span class="pill">{{ analysis.resolution_action }}</span>
    </div>
    <p class="text-sm mb-2" style="color: var(--text-primary);">{{ analysis.confirmed_root_cause }}</p>
    <div class="text-xs" style="color: var(--text-secondary);">
        <strong>Recommended fix:</strong> {{ analysis.recommended_fix }}
    </div>
</div>
```

- [ ] **Step 5: Create `web/templates/partials/reports/healing_entry.html`**

```html
<div class="flex items-start gap-3 p-3 rounded mb-2" style="background-color: var(--bg-primary); border: 1px solid var(--border);">
    <div class="mt-0.5">
        {% if action.success %}
        <div class="w-2.5 h-2.5 rounded-full" style="background-color: var(--accent-green);"></div>
        {% else %}
        <div class="w-2.5 h-2.5 rounded-full" style="background-color: var(--accent-red);"></div>
        {% endif %}
    </div>
    <div class="flex-1">
        <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-mono" style="color: var(--text-primary);">{{ action.anomaly_id }}</span>
            <span class="pill">{{ action.action_type }}</span>
            <span class="badge {% if action.success %}badge-completed{% else %}badge-errored{% endif %}">
                {% if action.success %}OK{% else %}FAILED{% endif %}
            </span>
        </div>
        <p class="text-sm" style="color: var(--text-secondary);">{{ action.explanation }}</p>
        {% if action.target_file %}
        <div class="text-xs mt-1 font-mono" style="color: var(--accent-cyan);">{{ action.target_file }}</div>
        {% endif %}
    </div>
</div>
```

- [ ] **Step 6: Create `web/templates/reports.html`**

```html
{% extends "base.html" %}
{% block title %}Reports & Analytics — QAura{% endblock %}

{% block content %}
<div class="p-8">
    <div class="text-xs font-semibold uppercase tracking-wider mb-1" style="color: var(--text-secondary);">Quality Intelligence</div>
    <h1 class="text-2xl font-bold mb-2" style="color: var(--accent-purple);">Reports & Analytics</h1>
    <p class="text-sm mb-8" style="color: var(--text-secondary);">Operational analytics for the autonomous testing pipeline.</p>

    <!-- KPI Cards -->
    {% include "partials/reports/kpi_cards.html" %}

    <div class="grid grid-cols-2 gap-6">
        <!-- Left column -->
        <div>
            {% include "partials/reports/execution_table.html" %}
            {% include "partials/reports/report_body.html" %}
        </div>

        <!-- Right column -->
        <div>
            <!-- Defect Analyses -->
            <div class="mb-6">
                <h3 class="font-semibold mb-3" style="color: var(--text-primary);">Defect Analyses</h3>
                {% if defect_analyses %}
                {% for analysis in defect_analyses %}
                {% include "partials/reports/defect_card.html" %}
                {% endfor %}
                {% else %}
                <div class="card p-5">
                    <p class="text-sm" style="color: var(--text-secondary);">No defects analyzed.</p>
                </div>
                {% endif %}
            </div>

            <!-- Healing Actions -->
            <div>
                <h3 class="font-semibold mb-3" style="color: var(--text-primary);">Healing Actions</h3>
                {% if healing_actions %}
                {% for action in healing_actions %}
                {% include "partials/reports/healing_entry.html" %}
                {% endfor %}
                {% else %}
                <div class="card p-5">
                    <p class="text-sm" style="color: var(--text-secondary);">No healing actions taken.</p>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Update reports route in `web/app.py`**

Replace the `reports_page` route:

```python
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

    return templates.TemplateResponse("reports.html", {
        "request": request,
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
```

- [ ] **Step 8: Verify reports page**

After a pipeline run completes, navigate to `http://localhost:8000/reports`. Expected: KPI cards with pass rate, coverage, anomaly count, healing rate. Execution summary with per-component scores. QA report rendered. Defect cards and healing entries if anomalies were found.

- [ ] **Step 9: Commit**

```bash
git add web/templates/reports.html web/templates/partials/reports/ web/app.py
git commit -m "feat(web): reports & analytics page with KPIs, defects, healing"
```

---

### Task 7: End-to-End Smoke Test & Polish

**Files:**
- Modify: `web/app.py` — minor fixes from testing
- Modify: `web/pipeline.py` — edge case handling

**Interfaces:**
- Consumes: all prior tasks
- Produces: verified end-to-end working system

- [ ] **Step 1: Full end-to-end test**

1. Start demo app: `cd demo_app && python -m uvicorn server:app --port 3000`
2. Start dashboard: `python -m uvicorn web.app:app --port 8000 --reload`
3. Open `http://localhost:8000`
4. Click "+ New Run" → enter path or leave blank → "Start Pipeline"
5. Watch timeline stream events in real-time
6. When approval card appears, review plan → click "Approve"
7. Watch remaining phases stream through
8. Navigate to Agent Logs → verify each agent tab shows its events
9. Navigate to Reports → verify KPI cards, execution table, QA report, defects, healing

- [ ] **Step 2: Verify CLI still works independently**

Run: `python core/graph.py`

Expected: interactive CLI pipeline runs without errors, unaffected by web changes.

- [ ] **Step 3: Verify no-run states**

Open each page without any pipeline run active:
- Dashboard: "No active run" placeholder
- Agent Logs: "No activity recorded" in each tab
- Reports: KPIs show "—", sections show "No data yet"

- [ ] **Step 4: Final commit**

```bash
git add -A web/
git commit -m "feat(web): complete HTMX frontend — dashboard, agents, reports with SSE"
```
