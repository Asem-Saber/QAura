# QAura HTMX Frontend — Design Spec

**Date:** 2026-06-28
**Status:** Approved
**Approach:** FastAPI + Jinja2 + HTMX + SSE (Approach A)

---

## Context & Constraints

- **Solo operator** — no auth, no multi-tenancy
- **Separate server** — QAura dashboard on port 8000, demo app stays on port 3000
- **Live SSE streaming** — real-time agent activity feed is essential
- **CLI preserved** — `python core/graph.py` stays as an alternative entry point
- **No JS build step** — HTMX and Tailwind loaded via CDN

---

## 1. Project Structure

```
web/
├── app.py                  # FastAPI app — all routes defined here
├── pipeline.py             # PipelineManager — run lifecycle, event queue, SSE bridge
├── templates/
│   ├── base.html           # Shared layout: dark theme, sidebar nav, HTMX + Tailwind CDN
│   ├── dashboard.html      # Frame 1: live pipeline timeline + run summary
│   ├── agents.html         # Frame 2: tabbed agent logs
│   ├── reports.html        # Frame 3: KPIs, QA report, defect cards, healing actions
│   └── partials/
│       ├── timeline/
│       │   ├── log_entry.html       # Single agent event (timestamp, badge, message, pills)
│       │   ├── phase_badge.html     # Phase indicator swap
│       │   └── approval_card.html   # Inline HITL approval form
│       ├── summary/
│       │   └── run_summary.html     # Right sidebar stats (tests, passed, failed, etc.)
│       ├── agents/
│       │   └── agent_tab.html       # Per-agent log content (tool calls, output)
│       └── reports/
│           ├── kpi_cards.html       # Top-row stat cards
│           ├── execution_table.html # Pass/fail/blocked per component
│           ├── report_body.html     # Rendered QA report markdown
│           ├── defect_card.html     # Single defect analysis card
│           └── healing_entry.html   # Single healing action entry
└── static/
    └── styles.css          # Custom CSS overrides (dark theme tokens, scrollbar, timeline line)
```

**Key decisions:**
- `web/app.py` imports from `core.graph` — thin HTTP layer over the existing pipeline API
- `web/pipeline.py` manages run state (active run config, SSE event queue) — keeps `app.py` focused on routes
- `partials/` contains HTML fragments that HTMX swaps in — no full-page reloads after initial load

---

## 2. Pages & Navigation

### Sidebar Navigation (persistent)

```
QAura
AGENTIC QA OPS

OPERATIONS
├── Pipeline Dashboard    ← Frame 1: live running view
├── Agent Logs            ← Frame 2: per-agent tool calls & output
└── Reports & Analytics   ← Frame 3: reporting + defect analysis
```

"New Run" button at the top of the sidebar.

### Frame 1: Pipeline Dashboard (Live Running)

**Layout:** Two-column — timeline (left, wide) + run summary sidebar (right, narrow)

**Left column — Run Timeline:**
- Chronological feed of agent events, streamed via SSE
- Each entry: timestamp, agent name (color-coded badge), status (running/completed), description
- Metadata pills below each entry (e.g., `Files 23`, `LOC +1,284`, `Risk Medium`)
- HITL approval appears inline as a card in the timeline — review plan, approve/reject with feedback, no page change

**Right column — Run Summary:**
- Static card updated via SSE as phases complete
- Shows: trigger info, duration, tests run, passed, failed, healed, escalated, coverage %
- Agent participation bars showing which agents have fired and event counts

### Frame 2: Agent Logs

**Layout:** Tabbed interface — one tab per agent

**Agents:** Test Architect, Unit Gen, E2E Gen, Execution, Reporting, Defect Intelligence, Self-Healing

**Each tab shows:**
- Agent status badge (idle / running / completed / errored)
- Collapsible log entries: tool calls with arguments, tool responses, final output
- Final structured output (e.g., `TestPlan` for Test Architect, `ExecutionOutput` for Execution)

**HTMX behavior:** Tab click does `hx-get="/partials/agents/{agent_name}/logs"` and swaps the panel. During a live run, active agent tab auto-updates via SSE.

### Frame 3: Reports & Analytics

**Layout:** KPI cards row + data grid + detailed sections

**Top row — KPI cards:**
- Pass Rate (passed/total)
- Coverage confidence (from `CoverageConfidenceAssessment`)
- Anomaly count
- Healing success rate

**Main grid:**
- Execution Summary — table of results with pass/fail/blocked per component
- QA Report — rendered markdown from reporting agent
- Defect Analyses — cards per `DefectAnalysis` with anomaly ID, root cause, classification badge, recommended fix
- Healing Actions — timeline of self-healing actions with success/fail status

**HTMX behavior:** Standard `hx-get` load. Unpopulated sections show skeleton placeholders, swapped via SSE when data arrives.

---

## 3. Data Flow & SSE Architecture

### Bridge: `web/pipeline.py`

```
User clicks "New Run"
        |
        v
    web/app.py          POST /runs
        |
        v
    web/pipeline.py     PipelineManager.start_run()
        |
        +---> core/graph.py   run_pipeline_phase1()
        |         |
        |         +-- astream() yields events
        |         |
        |         v
        +---> asyncio.Queue   <-- events pushed here
        |
        v
    SSE endpoint         GET /sse/pipeline/{run_id}
        |
        v
    HTMX sse extension   appends partials to DOM
```

### SSE Event Types

| SSE Event | Data | Partial Swapped |
|---|---|---|
| `phase_change` | `{phase, agent_name, status}` | `phase_badge.html` |
| `agent_log` | `{timestamp, agent, message, tool_calls}` | `log_entry.html` → appended to timeline |
| `stats_update` | `{total, passed, failed, ...}` | `run_summary.html` → replaces summary sidebar |
| `plan_ready` | `{plan_html}` (pre-rendered by PipelineManager via Jinja2) | `approval_card.html` → appended to timeline |
| `run_complete` | `{final_state}` | Triggers full results load |

### HITL Approval Flow

```
Pipeline hits interrupt
        |
        v
PipelineManager pushes "plan_ready" SSE event
        |
        v
HTMX appends approval card to timeline
(rendered plan + approve/reject buttons + feedback textarea)
        |
        v
User clicks Approve/Reject
        |
        v
HTMX POST /runs/{run_id}/approve  {approved, feedback}
        |
        v
web/pipeline.py sets asyncio.Event, pipeline resumes
        |
        v
run_pipeline_phase2() continues, SSE stream resumes
```

### State Storage

- **Active run state** — in-memory in `PipelineManager` (one run at a time)
- **Run history** — LangGraph `MemorySaver` checkpointer (per `thread_id`)
- **Reports** — written to `reports/` as markdown by the reporting agent

---

## 4. Route Definitions

### Page Routes (full HTML)

| Method | Path | Description |
|---|---|---|
| `GET /` | Redirect to `/dashboard` |
| `GET /dashboard` | Frame 1: Pipeline Dashboard |
| `GET /agents` | Frame 2: Agent Logs |
| `GET /reports` | Frame 3: Reports & Analytics |

### HTMX Partial Routes (HTML fragments)

| Method | Path | Description |
|---|---|---|
| `GET /partials/agents/{agent_name}/logs` | Per-agent log content (tab swap) |
| `GET /partials/reports/{run_id}` | Full report view for a run |
| `GET /partials/plan/{run_id}` | Rendered test plan for HITL |

### API Routes (actions)

| Method | Path | Description |
|---|---|---|
| `POST /runs` | Start pipeline. Body: `{requirements_path}`. Returns `run_id`, HX-Redirect to dashboard |
| `POST /runs/{run_id}/approve` | HITL approval. Body: `{approved, feedback}`. Unblocks pipeline |
| `GET /runs/{run_id}/state` | Current run state as JSON (debug/programmatic) |

### SSE Endpoint

| Method | Path | Description |
|---|---|---|
| `GET /sse/pipeline/{run_id}` | SSE stream for live updates |

### HTMX SSE Connection

```html
<div hx-ext="sse"
     sse-connect="/sse/pipeline/{{ run_id }}"
     sse-swap="agent_log"
     hx-target="#timeline"
     hx-swap="beforeend">
</div>
```

Multiple listeners on the same connection for different swap targets:
- `agent_log` → appends to `#timeline`
- `phase_change` → swaps `#phase-badge`
- `stats_update` → swaps `#run-summary`
- `plan_ready` → appends to `#timeline`
- `run_complete` → swaps `#run-status`

---

## 5. Dependencies

Added to `requirements.txt`:

| Package | Purpose |
|---|---|---|
| `uvicorn` | ASGI server |
| `jinja2` | Template engine |
| `sse-starlette` | SSE responses for FastAPI |

HTMX and Tailwind CSS loaded via CDN in `base.html`. No build step.

### How to Run

```bash
# Terminal 1: demo app (app under test)
uvicorn demo_app.server:app --port 3000

# Terminal 2: QAura dashboard
uvicorn web.app:app --port 8000 --reload
```

CLI alternative: `python core/graph.py`

---

## 6. Visual Design

### Dark Theme Tokens

| Token | Value | Used For |
|---|---|---|
| `--bg-primary` | `#0f1117` | Page background |
| `--bg-surface` | `#1a1d27` | Cards, sidebar, panels |
| `--bg-surface-hover` | `#242836` | Hover states |
| `--border` | `#2a2e3a` | Card borders, dividers |
| `--text-primary` | `#f0f0f0` | Headings, body text |
| `--text-secondary` | `#8b8fa3` | Subtitles, metadata |
| `--accent-purple` | `#a78bfa` | Page titles, active nav |
| `--accent-green` | `#4ade80` | Pass, success, completed |
| `--accent-red` | `#f87171` | Fail, error, blocked |
| `--accent-yellow` | `#fbbf24` | Warnings, medium risk |
| `--accent-blue` | `#60a5fa` | Info, links, integration |

### Agent Color Coding

| Agent | Color |
|---|---|
| Test Architect | `#a78bfa` (purple) |
| Unit Generator | `#4ade80` (green) |
| Integration Gen | `#60a5fa` (blue) |
| E2E Generator | `#fbbf24` (yellow) |
| Execution Runner | `#f97316` (orange) |
| Reporting | `#06b6d4` (cyan) |
| Defect Intelligence | `#f87171` (red) |
| Self-Healing | `#e879f9` (pink) |

### Component Patterns

**Sidebar:** Fixed left, ~220px. Logo + nav items with icons. Active item: left border accent + lighter background.

**KPI Cards:** Row of 4. Label (secondary text), large number (primary), trend indicator (green/red arrow + delta).

**Timeline Entries:** Vertical timeline with connecting line. Colored agent dot, timestamp + agent + status badge, description, metadata pills.

**Status Badges:** Pill-shaped with tinted background:
- `completed` — green
- `running` — blue (pulse animation)
- `errored` — red
- `idle` — gray

**Approval Card:** Elevated card with border accent in timeline. Rendered test plan (component table with risk colors), approve/reject buttons, feedback textarea.

### Tailwind Strategy

Tailwind via CDN handles 90% of styling. `styles.css` defines only:
- CSS custom properties (color tokens)
- Timeline vertical line connector
- SSE fade-in animation for new entries
- Dark scrollbar styling
- Pulse animation for "running" badges
