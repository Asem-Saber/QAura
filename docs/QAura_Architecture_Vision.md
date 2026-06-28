# QAura: Autonomous Software Testing & Self-Healing Multi-Agent System

## Complete Architecture Vision

> This document describes QAura's full architecture after incorporating all planned modifications:
> **LeanCTX MCP Integration**, **Long-Term Memory (LTM)**, **LangGraph Sub-Graph Agent Loops**,
> and the newly proposed **Defect Knowledge Graph**.

---

## 1. Project Overview

QAura is an autonomous, multi-agent AI system that models the entire **Software Testing Life Cycle (STLC)** as a continuous agent loop. Rather than executing brittle, hand-written test scripts, QAura deploys seven specialized agents orchestrated through a compiled LangGraph state machine. These agents plan, generate, execute, analyze, and self-heal tests — cycling through the loop until all tests pass or the system escalates to a human engineer.

### Core Capabilities (Post-Modification)

| Capability | Current Implementation | After Modifications |
|---|---|---|
| **Codebase Understanding** | ChromaDB + Ollama embeddings (`search_codebase`) | **LeanCTX MCP** — AST-aware, deduplicated, compressed context via `ctx_search`, `ctx_read`, `ctx_retrieve` |
| **Agent Architecture** | `AgentExecutor` (legacy LangChain) | **LangGraph Sub-Graphs** — each agent is a `create_react_agent` sub-graph with isolated `MessagesState` |
| **Historical Memory** | None (ephemeral per-run) | **Long-Term Memory (LTM)** — SQLite ledger tracking test executions, flakiness rates, and healing actions across runs |
| **Relationship Intelligence** | None | **Defect Knowledge Graph** — a graph structure mapping component dependencies, defect patterns, test coverage, and healing effectiveness |
| **Self-Healing** | Full Phase 5 loop with conditional routing | Enhanced with LTM-informed flakiness detection and Knowledge Graph-driven root cause correlation |
| **Multi-Dimensional Testing** | Unit (active), Integration & E2E (implemented, commented out) | All three generators active in parallel via `RunnableParallel`-style fan-out |

### Design Principles

1. **Macro/Micro Orchestration** — The high-level STLC workflow (macro) is a deterministic LangGraph state machine. Each agent internally runs an autonomous ReAct loop (micro) as a LangGraph sub-graph.
2. **State Isolation** — Agent sub-graphs operate on local `MessagesState`, preventing intermediate tool calls and scratchpad reasoning from bloating the shared `QAuraState`.
3. **Context Efficiency** — LeanCTX's AST-aware compression replaces raw vector search, reducing token usage by 60-80% while improving retrieval relevance.
4. **Persistent Intelligence** — The LTM + Knowledge Graph combination gives agents cross-run memory: flaky test history, proven healing patterns, and component risk propagation.
5. **Human-in-the-Loop (HITL)** — Strict approval gates at test plan review and application code merges ensure safety boundaries.

---

## 2. Project Structure

```
QAura/
├── agents/                          # Agent modules (one per STLC role)
│   ├── planning_agent.py            # Phase 1: Test Architect + HITL approval gate
│   ├── unit_test_gen.py             # Phase 2: Unit test generator
│   ├── integration_test_gen.py      # Phase 2: Integration test generator
│   ├── e2e_test_gen.py              # Phase 2: E2E & security test generator
│   ├── execution_agent.py           # Phase 3-4: Environment check + test runner
│   ├── reporting_agent.py           # Phase 4: QA report compiler
│   ├── defect_intelligence_agent.py # Phase 4: Root cause analyzer
│   └── self_healing_agent.py        # Phase 5: Auto-fix & loop-back controller
│
├── core/                            # Shared infrastructure
│   ├── graph.py                     # LangGraph state machine (macro orchestrator)
│   ├── state.py                     # QAuraState TypedDict + all Pydantic models
│   ├── tools.py                     # @tool definitions + tool lists per agent
│   ├── output_parsing.py            # robust_parse() — LLM-assisted JSON repair
│   ├── mcp_client.py                # [NEW] LeanCTX MCP client manager
│   └── memory_db.py                 # [NEW] SQLite long-term memory wrapper
│
├── knowledge_graph/                 # [NEW] Defect Knowledge Graph
│   ├── graph_store.py               # Graph data structure & persistence
│   ├── graph_builder.py             # Builds/updates graph from state events
│   └── graph_query.py               # Query interface exposed as agent tools
│
├── demo_app/                        # Application under test (FastAPI + SQLite)
│   ├── server.py                    # FastAPI routes and middleware
│   ├── auth.py                      # Authentication: register, login, sessions
│   ├── orders.py                    # Products, orders, calculations
│   ├── models.py                    # SQLite schema and seed data
│   └── templates/                   # HTML frontend (login, dashboard, etc.)
│
├── scripts/                         # Utility scripts
│   ├── codebase_vectordb.py         # [DEPRECATED] ChromaDB ingestion
│   └── codebase_rag.py              # [DEPRECATED] Standalone RAG query
│
├── tests/                           # Generated test files (output of Phase 2)
├── reports/                         # Generated QA reports (output of Phase 4)
├── conftest.py                      # Pytest path configuration
├── project_requirements.md          # Requirements for the demo app under test
├── .env.example                     # Environment variable template
└── QAura.md                         # Original project specification
```

### Key Changes from Current State

| Directory/File | Change | Reason |
|---|---|---|
| `core/mcp_client.py` | **New** | Synchronous wrapper around the async MCP SDK for LeanCTX |
| `core/memory_db.py` | **New** | SQLite-based long-term memory (test history + healing ledger) |
| `knowledge_graph/` | **New** | Defect Knowledge Graph for relationship intelligence |
| `core/tools.py` | **Modified** | Remove ChromaDB; add MCP tools (`ctx_search`, `ctx_read`, `ctx_retrieve`), LTM tools (`query_test_history`, `log_healing_action`), and KG tools (`query_component_dependencies`, `query_defect_patterns`) |
| `agents/*.py` | **Modified** | Replace `AgentExecutor` with `create_react_agent` sub-graphs; update prompts for LeanCTX tools |
| `scripts/` | **Deprecated** | ChromaDB ingestion no longer needed with LeanCTX |

---

## 3. The Defect Knowledge Graph — Introducing Relationship Intelligence

### Motivation

While the Long-Term Memory (LTM) stores **historical records** (flat rows: test X failed at time T with error E), it lacks the ability to answer **relational questions** like:

- *"Which components are most likely to break when `auth.py` changes?"*
- *"Has this exact root cause pattern been seen before in a different component?"*
- *"What healing strategy worked last time for this type of failure?"*

The **Defect Knowledge Graph (DKG)** fills this gap by modeling the semantic relationships between components, tests, defects, and healing actions as a directed graph.

### Graph Schema

```
Entities (Nodes):
  Component    — A source module (e.g., auth.py, orders.py)
  TestFile     — A generated test file (e.g., test_auth.py)
  Defect       — A specific anomaly instance (ANOM-001)
  HealingAction — A corrective action taken (TEST_PATCH, APP_FIX_DRAFT)
  RiskArea     — A domain risk (e.g., "SQL injection", "Session expiry")

Relationships (Edges):
  Component  --[DEPENDS_ON]-->   Component       (import/call dependencies)
  Component  --[BELONGS_TO]-->   RiskArea        (from test plan risk mapping)
  TestFile   --[COVERS]-->       Component       (test-to-component coverage)
  Defect     --[AFFECTS]-->      Component       (which component broke)
  Defect     --[DETECTED_BY]-->  TestFile        (which test caught it)
  Defect     --[CLASSIFIED_AS]--> str            (INFRASTRUCTURE | APP_DEFECT | DECAY)
  Defect     --[HAS_PATTERN]-->  Defect          (similar root cause signature)
  HealingAction --[FIXES]-->     Defect          (which defect was healed)
  HealingAction --[MODIFIES]-->  Component|Test  (what file was patched)
  HealingAction --[SUCCEEDED]--> bool            (did re-execution pass?)
```

### How Agents Use the Knowledge Graph

| Agent | Query | Value |
|---|---|---|
| **Test Architect** | `get_risk_propagation(component)` | When `auth.py` is changed, the KG shows that `orders.py` and `server.py` depend on it — so integration tests must cover those too |
| **Defect Intelligence** | `get_similar_defects(root_cause_signature)` | Before investigating from scratch, check if this failure pattern matches a previously diagnosed defect. Reuse the proven diagnosis |
| **Self-Healing** | `get_successful_healing_patterns(defect_type)` | Before attempting a fix, query which healing strategies have historically succeeded for this type of failure. Prioritize high-confidence approaches |
| **Reporting** | `get_component_health_score(component)` | Aggregate defect frequency, healing success rate, and flakiness into a per-component health score for the QA report |

### Implementation Approach

The DKG uses a lightweight in-memory graph structure (adjacency list) persisted to a JSON file. This avoids adding a heavyweight dependency like Neo4j while providing the relational query capability the agents need. The graph is built incrementally:

1. **At pipeline start** — `graph_builder.py` parses the test plan to create `Component` and `RiskArea` nodes with their relationships.
2. **After test generation** — `TestFile --[COVERS]--> Component` edges are added.
3. **After execution** — `Defect` nodes are created from anomaly reports.
4. **After healing** — `HealingAction` nodes record what was done, linked to both the defect and the modified file.
5. **Cross-run persistence** — The graph is serialized to JSON after each run and loaded at startup, accumulating knowledge over time.

---

## 4. Mermaid Chart — Full System Architecture

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#eef2ff', 'primaryBorderColor': '#4f46e5', 'lineColor': '#64748b'}}}%%
flowchart TB
    subgraph INPUT["Input Sources"]
        direction LR
        REQ["Git PR / Requirements"]
        CTX_DB[("LeanCTX MCP<br/>(AST-Aware Context)")]
        LTM_DB[("Long-Term Memory<br/>(SQLite)")]
        KG_DB[("Defect Knowledge<br/>Graph")]
    end

    subgraph PHASE1["Phase 1: Planning & Design"]
        direction TB
        TA["Test Architect Agent<br/><i>create_react_agent sub-graph</i>"]
        HITL1{{"HITL: Approve Plan?"}}
        ROUTER{"Route to<br/>Required Layers"}
        TA --> HITL1
        HITL1 -- "Reject/Modify" --> TA
        HITL1 -- "Approved" --> ROUTER
    end

    subgraph PHASE2["Phase 2: Parallel Test Generation"]
        direction TB
        UNIT["Unit Test<br/>Generator"]
        INTEG["Integration Test<br/>Generator"]
        E2E["E2E & Security<br/>Generator"]
        COMPILED["Shared State:<br/>Compiled Test Suites"]
        UNIT --> COMPILED
        INTEG --> COMPILED
        E2E --> COMPILED
    end

    subgraph PHASE3_4["Phase 3-4: Execution & Reporting"]
        direction TB
        ENV["Environment<br/>Health Check"]
        EXEC["Test Execution<br/>Runner"]
        REPORT["Reporting Agent"]
        DEFECT["Defect Intelligence<br/>Agent"]
        ENV --> EXEC --> REPORT
        REPORT -- "Anomalies Found" --> DEFECT
    end

    subgraph PHASE5["Phase 5: Self-Healing Loop"]
        direction TB
        HEAL["Self-Healing Agent"]
        DECISION{"Root Cause<br/>Classification"}
        TEST_PATCH["TEST_PATCH:<br/>Fix Test Script"]
        APP_FIX["APP_FIX_DRAFT:<br/>Fix App Code"]
        ESCALATE["ESCALATE:<br/>Human Engineer"]
        HITL2{{"HITL: Code Review"}}
        HEAL --> DECISION
        DECISION --> TEST_PATCH
        DECISION --> APP_FIX
        DECISION --> ESCALATE
        APP_FIX --> HITL2
    end

    subgraph OUTPUT["Outputs"]
        direction LR
        CI["CI/CD:<br/>Green Build"]
        QA_REPORT["QA Report<br/>(Markdown)"]
        TICKET["Escalation<br/>Ticket"]
    end

    %% Main flow
    REQ --> TA
    CTX_DB -.-> UNIT & INTEG & E2E & DEFECT & HEAL
    LTM_DB -.-> EXEC & DEFECT & REPORT
    KG_DB  -.-> TA & DEFECT & HEAL & REPORT

    ROUTER --> UNIT & INTEG & E2E
    COMPILED --> ENV

    %% Self-healing loop-back
    TEST_PATCH -- "Re-execute" --> EXEC
    HITL2 -- "Merged" --> UNIT
    REPORT -- "All Pass" --> CI
    REPORT --> QA_REPORT
    ESCALATE --> TICKET

    %% Loop counter guard
    HEAL -. "Max 3 iterations" .-> CI

    %% Styling
    style INPUT fill:#f8fafc,stroke:#94a3b8
    style PHASE1 fill:#eef2ff,stroke:#4f46e5
    style PHASE2 fill:#ecfeff,stroke:#22d3ee
    style PHASE3_4 fill:#f0fdf4,stroke:#4ade80
    style PHASE5 fill:#fff7ed,stroke:#fb923c
    style OUTPUT fill:#f0f9ff,stroke:#3b82f6
    style HITL1 fill:#fff1f2,stroke:#f43f5e,stroke-width:2px,stroke-dasharray:5 5
    style HITL2 fill:#fff1f2,stroke:#f43f5e,stroke-width:2px,stroke-dasharray:5 5
    style CTX_DB fill:#dbeafe,stroke:#3b82f6
    style LTM_DB fill:#fef3c7,stroke:#f59e0b
    style KG_DB fill:#ede9fe,stroke:#8b5cf6
```

---

## 5. Sequence Diagram — Full Pipeline Execution

```mermaid
sequenceDiagram
    autonumber
    participant User as Human / CI Trigger
    participant Graph as Macro Graph<br/>(LangGraph)
    participant TA as Test Architect<br/>(Sub-Graph)
    participant CTX as LeanCTX MCP
    participant UGen as Unit Generator<br/>(Sub-Graph)
    participant IGen as Integration Generator<br/>(Sub-Graph)
    participant EGen as E2E Generator<br/>(Sub-Graph)
    participant Exec as Execution Agent<br/>(Sub-Graph)
    participant LTM as Long-Term Memory<br/>(SQLite)
    participant Report as Reporting Agent<br/>(Sub-Graph)
    participant DIA as Defect Intelligence<br/>(Sub-Graph)
    participant KG as Knowledge Graph
    participant Heal as Self-Healing Agent<br/>(Sub-Graph)

    Note over User, Heal: Phase 1 — Planning & Design
    User->>Graph: Start pipeline (requirements_path)
    Graph->>TA: Invoke sub-graph
    TA->>TA: read_requirements_file()
    TA->>KG: get_risk_propagation() for component dependencies
    TA-->>Graph: TestPlan (components, scopes, risk_areas)
    Graph->>User: interrupt() — Review test plan
    User->>Graph: resume(approved=true)

    Note over Graph, EGen: Phase 2 — Parallel Test Generation
    par Fan-out to generators
        Graph->>UGen: unit_scope components
        UGen->>CTX: ctx_search(component)
        UGen->>CTX: ctx_read(file, mode=skeleton)
        UGen->>CTX: ctx_read(file, mode=full)
        UGen->>UGen: validate → write_test_file
        UGen-->>Graph: GeneratedTest[]
    and
        Graph->>IGen: integration_scope components
        IGen->>CTX: ctx_search(API routes)
        IGen->>CTX: ctx_read(models, mode=full)
        IGen->>IGen: validate → write_test_file
        IGen-->>Graph: GeneratedTest[]
    and
        Graph->>EGen: e2e_scope components
        EGen->>CTX: ctx_search(templates)
        EGen->>CTX: ctx_read(routes, mode=skeleton)
        EGen->>EGen: validate_selenium_locators → write_test_file
        EGen-->>Graph: GeneratedTest[]
    end

    Note over Graph, LTM: Phase 3-4 — Execution & Reporting
    Graph->>Exec: Compiled test suites
    Exec->>Exec: check_environment_health()
    Exec->>Exec: run_pytest_suite("tests/")
    Exec->>LTM: log_execution(test_id, duration, pass/fail)
    Exec-->>Graph: ExecutionOutput (summary, anomalies)

    Graph->>Report: Execution results
    Report->>LTM: query_test_history() for flakiness context
    Report->>KG: get_component_health_score()
    Report->>Report: write_report_file()
    Report-->>Graph: QAReport

    alt Anomalies detected
        Graph->>DIA: anomaly_reports[]
        DIA->>CTX: search source code for affected components
        DIA->>DIA: read_test_file() + read_server_log()
        DIA->>KG: get_similar_defects(root_cause_signature)
        DIA-->>Graph: DefectAnalysis[] with resolution_actions

        Note over Graph, Heal: Phase 5 — Self-Healing Loop
        Graph->>Heal: defect_analyses[]
        Heal->>KG: get_successful_healing_patterns(defect_type)
        Heal->>CTX: read source + test context
        Heal->>Heal: write_patch_file() (test or app code)
        Heal->>LTM: log_healing_action()
        Heal->>KG: record healing outcome
        Heal-->>Graph: SelfHealingOutput

        alt TEST_PATCH applied
            Graph->>Exec: Re-execute (loop back to Phase 4)
        else APP_FIX_DRAFT applied
            Graph->>User: HITL — Code review & merge
            User->>Graph: Approved
            Graph->>UGen: Re-generate tests (loop back to Phase 2)
        else ESCALATE or max retries
            Graph->>User: Escalation ticket
        end
    else All tests pass
        Graph->>User: CI/CD Green Build + QA Report
    end
```

---

## 6. Agent Graph Structure & Workflow

### 6.1 Macro Orchestration — The STLC State Machine

The macro graph is a compiled `StateGraph` that manages the high-level workflow. It uses `QAuraState` (a `TypedDict`) as shared memory, with Pydantic models ensuring structured communication between agents.

```
State Machine Transitions:

  START
    │
    ▼
  test_architect ─────────────────────────────────────────────┐
    │                                                         │
    ▼                                                         │
  human_approval ──(rejected)──────────────────────────► END  │
    │                                                         │
    │ (approved)                                              │
    ▼                                                         │
  ┌─────────────────────────────────────┐                     │
  │  PARALLEL FAN-OUT (Phase 2)        │                     │
  │  ┌─── unit_test_gen ───┐           │                     │
  │  ├─── integration_gen ──┤ ──► JOIN │                     │
  │  └─── e2e_gen ─────────┘           │                     │
  └────────────────────────────────────┘                     │
    │                                                         │
    ▼                                                         │
  execution_agent                                             │
    │                                                         │
    ▼                                                         │
  reporting_agent ──(no anomalies)──────────────────────► END │
    │                                                         │
    │ (anomalies found)                                       │
    ▼                                                         │
  defect_intelligence_agent                                   │
    │                                                         │
    ▼                                                         │
  self_healing_agent                                          │
    │                                                         │
    ├──(healed / escalated / max_retries=3)──────────────► END│
    │                                                         │
    ├──(TEST_PATCH only)──► execution_agent  (loop Phase 4)   │
    │                                                         │
    └──(APP_FIX_DRAFT)────► unit_test_gen   (loop Phase 2) ──┘
```

### 6.2 Micro Orchestration — The ReAct Agent Sub-Graph

After the Agent Loop refactoring, each agent internally runs as a **LangGraph sub-graph** using `create_react_agent`. This replaces the legacy `AgentExecutor`.

```
┌─────────────────────────────────────────────────┐
│  Agent Sub-Graph (e.g., Unit Test Generator)    │
│                                                 │
│    ┌─────────────┐                              │
│    │   START      │                              │
│    └──────┬──────┘                              │
│           ▼                                      │
│    ┌─────────────┐      ┌───────────────┐       │
│    │  LLM Call   │─────►│  Tool Calls   │       │
│    │  (Reason)   │◄─────│  (Act)        │       │
│    └──────┬──────┘      └───────────────┘       │
│           │ (loop until done)                    │
│           ▼                                      │
│    ┌─────────────┐                              │
│    │  Final      │                              │
│    │  Response   │                              │
│    └──────┬──────┘                              │
│           ▼                                      │
│    ┌─────────────┐                              │
│    │   END        │                              │
│    └─────────────┘                              │
│                                                 │
│  Internal State: MessagesState (isolated)       │
│  External I/O:   Returns final text to macro    │
└─────────────────────────────────────────────────┘
```

**Bridge Pattern** — The macro node function acts as a translator:
1. Extracts relevant fields from `QAuraState` into a human prompt.
2. Invokes the sub-graph with `{"messages": [("user", prompt)]}`.
3. Parses the final message via `robust_parse()` into a Pydantic model.
4. Returns a dict that updates `QAuraState`.

### 6.3 Agent Inventory

| Agent | Phase | Sub-Graph Tools | Input from State | Output to State |
|---|---|---|---|---|
| **Test Architect** | 1 | `read_requirements_file`, KG: `get_risk_propagation` | `requirements_path` | `test_plan` |
| **HITL Approval** | 1 | *(interrupt gate)* | `test_plan` | `plan_approved` |
| **Unit Test Gen** | 2 | `ctx_search`, `ctx_read`, `ctx_retrieve`, `validate_python_syntax`, `validate_imports`, `check_test_structure`, `write_test_file` | `test_plan.unit_scope` | `unit_tests` |
| **Integration Test Gen** | 2 | `ctx_search`, `ctx_read`, `ctx_retrieve`, `validate_python_syntax`, `validate_imports`, `check_test_structure`, `write_test_file` | `test_plan.integration_scope` | `integration_tests` |
| **E2E & Security Gen** | 2 | `ctx_search`, `ctx_read`, `ctx_retrieve`, `validate_python_syntax`, `validate_imports`, `check_test_structure`, `write_test_file`, `validate_selenium_locators` | `test_plan.e2e_scope` | `e2e_tests` |
| **Execution Agent** | 3-4 | `check_environment_health`, `run_pytest_suite`, LTM: `log_execution` | `unit_tests`, `integration_tests`, `e2e_tests` | `execution_summary`, `coverage_assessment`, `anomaly_reports`, `execution_memory` |
| **Reporting Agent** | 4 | `write_report_file`, `get_timestamp`, LTM: `query_test_history`, KG: `get_component_health_score` | `execution_summary`, `coverage_assessment`, `anomaly_reports` | `qa_report`, `report_path` |
| **Defect Intelligence** | 4 | `ctx_search`, `read_test_file`, `read_server_log`, KG: `get_similar_defects` | `anomaly_reports` | `defect_analyses` |
| **Self-Healing Agent** | 5 | `ctx_search`, `read_test_file`, `read_source_file`, `write_patch_file`, `validate_python_syntax`, `validate_imports`, `check_test_structure`, `search_git_log`, KG: `get_successful_healing_patterns`, LTM: `log_healing_action` | `defect_analyses` | `healing_actions`, `healing_status`, `healing_loop_count` |

### 6.4 Shared State Schema (`QAuraState`)

```python
class QAuraState(TypedDict):
    # Phase 1 — Planning
    requirements_path: str
    test_plan: TestPlan | None
    plan_approved: bool
    messages: Annotated[list, operator.add]     # Append-only log

    # Phase 2 — Test Generation
    unit_tests: List[GeneratedTest]
    integration_tests: List[GeneratedTest]
    e2e_tests: List[GeneratedTest]

    # Phase 3-4 — Execution & Reporting
    environment_status: dict
    execution_summary: ExecutionResultsSummary | None
    coverage_assessment: CoverageConfidenceAssessment | None
    anomaly_reports: List[StructuredAnomalyReport]
    execution_memory: List[ExecutionMemoryUpdate]
    qa_report: QAReport | None
    report_path: str

    # Phase 4 — Defect Analysis
    defect_analyses: List[DefectAnalysis]

    # Phase 5 — Self-Healing
    healing_actions: List[HealingAction]
    healing_loop_count: int                     # Max 3 iterations
    healing_status: str                         # healed | escalated | partial
```

### 6.5 Data Layer Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Agent Layer                               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐        │
│  │Planning│ │ Unit   │ │ Exec   │ │ Defect │ │ Heal   │  ...   │
│  └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘        │
│      │          │          │          │          │               │
├──────┼──────────┼──────────┼──────────┼──────────┼───────────────┤
│      │   Tool Layer (@tool wrappers)  │          │               │
│      │          │          │          │          │               │
│  ┌───▼──────────▼──┐  ┌───▼───┐  ┌───▼──────────▼───┐          │
│  │  LeanCTX MCP    │  │  LTM  │  │ Knowledge Graph  │          │
│  │  (ctx_search,   │  │(SQLite│  │ (JSON-persisted  │          │
│  │   ctx_read,     │  │ log,  │  │  adjacency list) │          │
│  │   ctx_retrieve) │  │ query)│  │                  │          │
│  └────────┬────────┘  └───┬───┘  └────────┬─────────┘          │
│           │               │               │                     │
│  ┌────────▼────────┐  ┌───▼──────────┐  ┌─▼──────────────┐     │
│  │ lean-ctx mcp    │  │ history.     │  │ defect_graph.  │     │
│  │ (subprocess)    │  │ sqlite3      │  │ json           │     │
│  └─────────────────┘  └──────────────┘  └────────────────┘     │
└──────────────────────────────────────────────────────────────────┘
```

### 6.6 The Self-Healing Loop — Decision Tree

```mermaid
flowchart TD
    A[Self-Healing Agent receives DefectAnalysis list] --> B{Loop count >= 3?}
    B -- Yes --> Z[END: Max retries reached]
    B -- No --> C{For each DefectAnalysis}

    C --> D{resolution_action?}

    D -- SELF_HEAL_LOCATOR --> E[Read failing test]
    E --> F[Query LeanCTX for current component state]
    F --> G[Query KG: similar past fixes?]
    G --> H[Generate corrected test code]
    H --> I[Validate syntax + imports + structure]
    I -- Fail --> H
    I -- Pass --> J[write_patch_file to tests/]
    J --> K[Record: action_type = TEST_PATCH]

    D -- SELF_HEAL_LOGIC --> L[Read buggy source file]
    L --> M[Query LeanCTX for related modules]
    M --> N[Query KG: successful fix patterns?]
    N --> O[Draft minimal application fix]
    O --> P[Validate syntax]
    P -- Fail --> O
    P -- Pass --> Q[write_patch_file to demo_app/]
    Q --> R[Record: action_type = APP_FIX_DRAFT]

    D -- ESCALATE_HUMAN --> S[Record: action_type = ESCALATE]
    D -- NO_ACTION --> T[Record: action_type = NO_ACTION]

    K --> U{All defects processed?}
    R --> U
    S --> U
    T --> U
    U -- No --> C
    U -- Yes --> V{Determine routing}

    V -- "TEST_PATCH only" --> W[Route to execution_agent<br/>Re-run tests]
    V -- "APP_FIX_DRAFT present" --> X[Route to unit_test_gen<br/>Re-generate + re-run]
    V -- "healed / escalated" --> Z

    W --> A
    X --> A
```

---

## 7. Summary of All Modifications

| Modification | What It Adds | Impact |
|---|---|---|
| **LeanCTX MCP** | AST-aware code search via MCP protocol | Replaces ChromaDB; reduces token usage 60-80%; eliminates Ollama dependency |
| **LangGraph Sub-Graphs** | Each agent becomes a `create_react_agent` sub-graph | State isolation; modern architecture; fine-grained checkpointing |
| **Long-Term Memory** | SQLite-backed test execution history and healing ledger | Cross-run flakiness detection; historical healing success rates |
| **Defect Knowledge Graph** | Relationship graph mapping components, defects, tests, and healing patterns | Dependency-aware risk propagation; pattern-based root cause correlation; healing strategy recommendation |

Together, these modifications transform QAura from a **single-run pipeline** into a **continuously learning testing system** that gets smarter with every execution cycle.
