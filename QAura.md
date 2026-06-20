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

### The Agentic Workflow Phases:
1.  **Phase 1: Planning & Design:** The `Test Architect Agent` evaluates a Git PR or requirement set, drafting a prioritized test plan. This requires a HITL approval gate before proceeding.
2.  **Phase 2: Creating Test Cases:** Using `RunnableParallel` routing, specialized agents (`Unit`, `Integration`, `E2E/Security`) concurrently generate tests, compiling them into a shared dictionary state.
3.  **Phase 3: Environment Setup:** A deterministic tool provisions the sandbox, seeds the database, and readies the application for execution.
4.  **Phase 4: Execution & Reporting:** The runner executes the compiled suite. A `Reporting Agent` compiles the execution metrics. Passing builds proceed to CI/CD. Failures are routed to the `Defect Intelligence Agent`.
5.  **Phase 5: Intelligent Self-Healing:** The `Self-Healing Agent` acts on the analyzer's root cause diagnosis:
    * *DOM/Locator Drift:* The test script is updated and re-run (up to a Max Retry limit).
    * *Logic Bug:* A Git PR is drafted for the application code (requires HITL review).
    * *Complex Bug:* Escalated to a human engineer.

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