# QAuro: Autonomous Software Testing & Self-Healing Multi-Agent System

## 1. Project Idea
QAuro is an advanced, multi-agent AI system designed to autonomously perform comprehensive software testing—spanning unit, integration, end-to-end (E2E), and security testing—while natively incorporating self-healing capabilities. Serving as a robust implementation of agentic AI principles, QAuro shifts away from brittle, statically scripted tests. Instead, it utilizes specialized agents to understand context, dynamically generate test suites aligned with the Software Testing Life Cycle (STLC), detect root causes of failures, and automatically heal broken tests or draft application code fixes. 

**Core Value Proposition:**
* **Self-Healing:** Automatically updates test locators and scripts when UI/DOM elements drift, avoiding false-positive pipeline failures.
* **Retrieval-Augmented Generation (RAG):** Integrates semantic search over the codebase, API contracts, and requirements to bypass context limits and ensure accurate, hallucination-free test generation and analysis.
* **Multi-Dimensional Testing:** Simultaneously validates logic, DOM structure, visual layout, and security vulnerabilities.
* **Intelligent Prioritization & Routing:** Uses a compiled state graph to intelligently route tasks and evaluate regression risks.
* **Root Cause Analysis:** Consolidates logs, DOM snapshots, and visual data to pinpoint exact failure origins.
* **Human-in-the-Loop (HITL):** Enforces strict boundaries for test planning approval and application code merges to ensure safety.

---

## 2. Project Structure
The system architecture follows a compiled state graph approach, modeling the Software Testing Life Cycle. The orchestration is structured using explicit parallel execution branches and dictionary-mapping state updates to ensure strict control over shared memory and context.

### Knowledge Retrieval Pipeline (RAG)
To support the agents dynamically, QAura incorporates a RAG pipeline:
1. **Ingestion Engine:** Parses and chunks the codebase (using AST) and documentation.
2. **Vector Database:** Stores embeddings (e.g., ChromaDB, Qdrant) for semantic search.
3. **Retrieval Tools:** Provides agents with tools like `search_codebase` or `search_api_docs` to fetch relevant context on-demand.

### Macro vs. Micro Orchestration (The Agent Loop)
To maintain both strict control over the testing lifecycle and autonomous flexibility for individual tasks, QAura employs a dual-graph architecture:
1. **Macro Orchestration (The Workflow Graph):** The high-level state graph that models the STLC phases (Planning -> Generation -> Execution -> Healing). It uses explicit parallel execution branches and dictionary-mapping state updates to manage the global state.
2. **Micro Orchestration (The Agent Loop):** Each individual agent operates as its own isolated LangGraph sub-graph. Inside this sub-graph, the agent executes a cyclic **ReAct (Reason + Act) loop**. This allows the agent to continuously call tools (e.g., executing a test or querying the RAG pipeline), evaluate the tool's output, and decide on the next step autonomously before returning a finalized result back to the Macro graph.

### The Continuous Macro Agent Loop (Phases 1 to 5):
Unlike traditional linear CI/CD pipelines, QAura models the entire Software Testing Life Cycle as a continuous, autonomous **Agent Loop**. The system cycles through these phases, continuously observing, evaluating, and reacting to the codebase state until all tests pass:

1.  **Phase 1: Planning & Design (Observe & Plan):** The `Test Architect Agent` evaluates a new Git PR or requirement set, drafting a prioritized test plan. This establishes the goal state (requires a HITL approval gate).
2.  **Phase 2: Creating Test Cases (Act - Generation):** Using `RunnableParallel` routing, specialized agents (`Unit`, `Integration`, `E2E/Security`) concurrently generate tests to fulfill the plan, compiling them into a shared dictionary state.
3.  **Phase 3: Environment Setup:** A deterministic tool provisions the sandbox, seeds the database, and readies the application for execution.
4.  **Phase 4: Execution & Reporting (Evaluate):** The runner executes the compiled suite. A `Reporting Agent` compiles metrics. Passing builds break the loop and proceed to CI/CD. Failures are routed to the `Defect Intelligence Agent` for root-cause analysis.
5.  **Phase 5: Intelligent Self-Healing (React & Loop Back):** The `Self-Healing Agent` acts on the analyzer's diagnosis to close the loop:
    * *DOM/Locator Drift:* The test script is updated and **the loop returns to Phase 4** to re-run the tests.
    * *Logic Bug:* A Git PR is drafted for the application code. Once approved/merged, **the loop returns to Phase 1 or 2** to re-evaluate the code.
    * *Missing Coverage:* If the intelligence agent finds gaps, **the loop returns to Phase 2** to draft missing tests.
    * *Complex Bug:* Escalated to a human engineer, pausing the loop.

---

## 3. The QAura Agents

The core of QAura relies on specialized agents orchestrated via a state graph, as illustrated below:

![QAura HITL Workflow](./QAura-mermaid.png)

Based on our architecture, the system utilizes the following distinct agents:

* **Test Architect Agent (Phase 1)**
  * **Role:** Acts as the principal planner.
  * **Function:** Ingests Git PRs or requirement documents, defines the testing pyramid scope, and intelligently routes execution to the required test layers. Uses RAG to query requirements (Jira, Confluence) to align tests with business logic.

* **Unit Test Generator (Phase 2)**
  * **Role:** Specialized code-level test creator.
  * **Function:** Operates explicitly in parallel when "Unit Scope" is defined, generating isolated unit tests which are compiled into the shared state. Utilizes RAG to fetch accurate interfaces and dependencies for precise mocking.

* **Integration Test Generator (Phase 2)**
  * **Role:** Cross-component tester.
  * **Function:** Operates explicitly in parallel when "Integration Scope" is defined, generating tests that validate the interaction between different modules or services. Uses RAG to retrieve API contracts and cross-module dependencies.

* **E2E & Security Generator (Phase 2)**
  * **Role:** End-user and security validator.
  * **Function:** Operates explicitly in parallel when "E2E / Security Scope" is defined, generating end-to-end user flows and vulnerability checks. Leverages RAG to query OpenAPI specs, GraphQL schemas, and UI libraries for structural accuracy.

* **Reporting Agent (Phase 4 & 5)**
  * **Role:** Metrics and communication compiler.
  * **Function:** Gathers execution results (pass/fail, coverage, defect summaries) and generates comprehensive reports for human stakeholders. It operates across both Phase 4 (execution metrics) and Phase 5 (tracking self-healing actions and escalations).

* **Defect Intelligence Agent (Phase 4)**
  * **Role:** Root cause analyzer.
  * **Function:** In the event of a failed execution, this agent analyzes logs, DOM snapshots, and traces to pinpoint the exact layer and cause of failure. Employs RAG to search server logs and recent Git commits for precise debugging context.

* **Self-Healing Agent (Phase 5)**
  * **Role:** Auto-fix initiator.
  * **Function:** Based on the root cause analysis, this agent takes corrective action. It updates test scripts for simple locator/DOM drift, drafts application code fix PRs for logic bugs, or escalates complex/systemic issues to a human engineer.