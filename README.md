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

![QAura HITL Workflow](./QAura-mermaid.png)

The system architecture follows a compiled state graph approach (via LangGraph), modeling the Software Testing Life Cycle. The orchestration is structured using explicit parallel execution branches and dictionary-mapping state updates to ensure strict control over shared memory and context.

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

## 3. What We Have Done So Far

We have successfully established the foundation of the agentic workflow and implemented Phase 1 and Phase 2 agents:

1. **Core State & Graph Architecture:** 
   - Defined `QAuraState` (`core/state.py`) to manage state across nodes, encompassing the Test Plan, generated tests, and human-in-the-loop approvals.
   - Set up the environment and LangChain/LangGraph configurations.
2. **Test Architect Agent (Planning_agent.py):**
   - Implemented the planner that reads requirements and outputs a structured `TestPlan`.
   - Included HITL (Human-in-the-loop) gates to review and approve the generated test plan.
3. **Test Generation Agents:**
   - **Unit Test Generator** (`unit_test_gen.py`): Parses the unit scope and uses tools to fetch implementations and draft mock-heavy pytest files.
   - **Integration Test Generator** (`integration_test_gen.py`): Focuses on cross-module interactions and database states without mocking.
   - **E2E Test Generator** (`e2e_test_gen.py`): Writes complete Selenium WebDriver journeys based on frontend templates and routes discovered by RAG tools.
4. **Agent Testing Infrastructure:**
   - Created standalone executable scripts (`test_agents/`) to test each agent individually and in pipelines (`Planning -> Unit`, `Planning -> Integration`, `Planning -> E2E`).

---

## 4. Next Steps

Moving forward, our immediate priorities include completing the system loop:

* **[ ] Implement Remaining Agents:**
  - Build the **Reporting Agent** to compile results.
  - Build the **Defect Intelligence Agent** to perform root cause analysis on failed executions.
  - Build the **Self-Healing Agent** to patch locator drift or draft code fixes.
* **[ ] Complete Phase 3 Environment Provisioning:**
  - Build sandbox/deterministic setup tools to deploy a real app target before execution.
* **[ ] Full Graph Orchestrator:**
  - Combine all isolated pipelines into a single, cohesive LangGraph script mapping all 5 phases sequentially.
* **[ ] Deepen RAG Integration:**
  - Finalize ingestion to our vector db (Chroma/Qdrant) and wire `search_codebase` tools seamlessly.
* **[ ] End-to-End Validation:**
  - Test the full multi-agent system against a sample vulnerable application to prove self-healing and test-generation end-to-end.
