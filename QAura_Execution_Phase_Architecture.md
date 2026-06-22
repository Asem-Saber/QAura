# Phase 3: Execution Agent Architecture

## Vision & Design Philosophy
The Execution Phase is the powerhouse of the QAura multi-agent QA team. Unlike traditional deterministic execution pipelines where tests run in a static, predefined sequence, the **Execution Agent** is an intelligent, autonomous orchestrator. It continuously observes, reasons, adapts, and makes decisions dynamically throughout the execution lifecycle.

Its mission is to evaluate what should be executed next, identify which tests provide the highest value based on evolving risk profiles, estimate true confidence-based coverage, and distinguish between application defects and infrastructure anomalies in real time.

---

## 1. Inputs from Phase 2 → Phase 3 (Contract)
The Execution Agent receives structured intelligence from the prior phases to drive its reasoning. This is the complete input contract.

### 1.1 `Prioritized_Test_Plan`
* **Purpose:** Provides strategic guidance on component boundaries, risk levels, and business priorities.
* **Producer Agent:** Test Architect Agent (Phase 1)
* **Conceptual Schema:** 
  `{ "components": [{ "id", "name", "risk_level" (High/Med/Low), "business_criticality" }] }`
* **Confidence Score:** N/A (Static Plan)
* **Required vs Optional:** **Required**
* **Influence on Execution:** Dictates the initial baseline weighting. High-risk components are prioritized early in the queue.

### 1.2 `Compiled_Test_Suites`
* **Purpose:** The generated, executable test artifacts mapped to specific targets.
* **Producer Agent:** Unit, Integration, and E2E Test Generators (Phase 2)
* **Conceptual Schema:** 
  `{ "test_id", "layer" (unit|integration|e2e), "target_component", "executable_path", "tags", "generation_confidence" }`
* **Confidence Score:** Provided by Phase 2 agents (e.g., `0.85` confidence that the test is robust).
* **Required vs Optional:** **Required**
* **Influence on Execution:** Forms the initial unranked pool of tasks. Tests with lower generation confidence may be monitored more strictly for flakiness.

### 1.3 `Dependency_Graph_Analysis`
* **Purpose:** Logical mapping of service and component interactions (e.g., `demo_app/orders.py` depends on `demo_app/auth.py`).
* **Producer Agent:** Test Architect Agent / Knowledge Retrieval Pipeline (Phase 1/2)
* **Conceptual Schema:** 
  `{ "nodes": ["auth", "orders", "db"], "edges": [{"source": "auth", "target": "orders"}] }`
* **Confidence Score:** `0.95` (Derived from static AST analysis)
* **Required vs Optional:** **Required**
* **Influence on Execution:** Drives cascading prioritization. If a core dependency (like Authentication) fails its unit/integration tests, the agent autonomously deprioritizes or skips downstream E2E workflows to save execution cost and reduce noise.

### 1.4 `Historical_Execution_Memory`
* **Purpose:** Insights from past runs regarding flakiness, duration, and infrastructure reliability.
* **Producer Agent:** RAG / Shared Memory Database
* **Conceptual Schema:** 
  `{ "test_id", "historical_failure_rate", "flaky_score", "average_duration_ms" }`
* **Confidence Score:** Varies based on sample size of past runs.
* **Required vs Optional:** **Optional** (Defaults to baseline if unavailable)
* **Influence on Execution:** Helps optimize execution time. Historically flaky tests might be grouped or retried differently. Long-running, low-risk tests are scheduled when infrastructure load is low.

### 1.5 `Environment_Status_Context`
* **Purpose:** Real-time health metrics of the execution infrastructure.
* **Producer Agent:** Environment Manager Tool (Phase 3 Startup)
* **Conceptual Schema:** 
  `{ "runners_available", "db_connected", "network_latency", "base_url" }`
* **Confidence Score:** `1.0` (Real-time telemetry)
* **Required vs Optional:** **Required**
* **Influence on Execution:** Prevents useless execution. If DB connection drops, execution is paused rather than generating 100+ false-positive test failures.

---

## 2. Agentic Test Prioritization
The Execution Agent abandons static FIFO queues in favor of a dynamic, continuously evolving prioritization engine.

* **Initial Ranking:** Tests are scored based on `risk_level`, `business_criticality`, and `historical_failure_rate`.
* **Runtime Reprioritization:** 
  * **Risk Escalation:** If a boundary value unit test fails, the agent dynamically elevates the priority of related integration and E2E tests for that same component to map the full impact radius.
  * **Dependency Pruning:** If a core service goes down, dependent UI tests are instantly deprioritized or blocked.
  * **Cost/Value Optimization:** As infrastructure load increases, the agent prioritizes fast, high-confidence unit tests over expensive, long-running UI workflows, ensuring maximum coverage given resource constraints.
  * **Flakiness Quarantine:** Tests exhibiting erratic runtime behavior (flaky) are dynamically moved to a quarantined retry queue to avoid blocking the critical path.

---

## 3. Intelligent Coverage Assessment
Coverage is no longer just "lines of code." The Execution Agent calculates **Confidence-Based Coverage** using runtime evidence.

* **Execution Evidence:** Evaluates API endpoints actually exercised, DOM elements interacted with, and database state mutations observed during the run.
* **Risk-Weighted Coverage:** A 90% pass rate on a Low-Risk component yields a lower overall coverage confidence than an 80% pass rate on a High-Risk Authentication module.
* **Workflow Confidence:** Tracks full user journeys. If unit tests pass but the E2E workflow fails, the coverage score for the integrated capability is penalized.
* **Dynamic Evolution:** The coverage score fluctuates in real-time. Skipped tests due to upstream failures immediately drop the coverage confidence of the affected downstream features.

---

## 4. Intelligent Log Analysis
Raw logs are transformed into structured intelligence during the execution phase to eliminate noise for downstream agents.

* **Log Collection:** Aggregates stdout, application server logs, DB traces, and network payloads in real-time.
* **Normalization & Correlation:** Correlates the exact timestamp of a test failure with the corresponding backend server logs to pinpoint the exact exception.
* **Anomaly Classification:** The agent uses an LLM-driven diagnostic prompt to categorize the failure:
  * `INFRASTRUCTURE`: e.g., `503 Service Unavailable`, `Connection Refused` -> Triggers agentic pause/retry.
  * `APPLICATION_DEFECT`: e.g., `AssertionError`, `IndexError` -> Sent to Defect Intelligence.
  * `TEST_SCRIPT_DECAY`: e.g., `ElementNotFoundException` -> Sent to Self-Healing.
* **Evidence Extraction:** Autonomously captures DOM snapshots, HAR network files, and screenshots the moment an anomaly is detected.

---

## 5. Agentic Reasoning Loop
The Execution Agent operates on a continuous, stateful loop until the dynamic queue is resolved or a hard constraint is hit.

1. **Observe:** Read infrastructure health, queue state, and memory.
2. **Analyze:** Evaluate if current coverage goals or risk profiles have shifted based on recent test outcomes.
3. **Prioritize:** Rerank the execution queue based on the latest intelligence.
4. **Execute:** Dispatch the highest-value test to a runner.
5. **Collect Evidence:** Await results; if failed, capture logs, traces, and DOM state.
6. **Evaluate Coverage:** Recalculate Intelligent Coverage Confidence based on the outcome.
7. **Analyze Logs:** Classify failures (Infra vs Application).
8. **Update Memory:** Store results in short-term context.
9. **Decide Next Action:** Loop back to Observe, or escalate a critical blocker.

---

## 6. Outputs from Phase 3 → Phase 4 (Contract)
The Execution Agent packages its findings into structured schemas, ensuring Phase 4 agents (Reporting & Defect Intelligence) do not need to re-parse raw data.

### 6.1 `Execution_Results_Summary`
* **Purpose:** High-level metrics for reporting and CI/CD pipelines.
* **Conceptual Schema:** 
  `{ "total_tests", "passed", "failed", "blocked", "execution_duration_ms", "critical_path_success" }`
* **Producer:** Execution Agent
* **Consumer:** Reporting Agent (Phase 4)
* **Confidence Score:** `1.0` (Deterministic metrics)
* **Supporting Evidence:** Start/End timestamps, runner node IDs.

### 6.2 `Coverage_Confidence_Assessment`
* **Purpose:** Risk-weighted estimate of the application's quality based on execution evidence.
* **Conceptual Schema:** 
  `{ "overall_confidence": 0.82, "component_scores": [{"component": "auth", "score": 0.95}], "identified_gaps": ["orders API"] }`
* **Producer:** Execution Agent
* **Consumer:** Reporting Agent / Phase 1 Architect (for next iteration)
* **Confidence Score:** Agent's estimated confidence in the assessment (e.g., `0.85`).
* **Supporting Evidence:** Executed workflow traces, skipped dependencies.

### 6.3 `Structured_Anomaly_Report`
* **Purpose:** Highly structured, pre-classified intelligence regarding any failures.
* **Conceptual Schema:** 
  `{ "anomaly_id", "test_id", "affected_component", "classification" (INFRA|LOGIC|DRIFT), "root_cause_hypothesis", "correlated_stack_trace" }`
* **Producer:** Execution Agent
* **Consumer:** Defect Intelligence Agent (Phase 4)
* **Confidence Score:** Agent's confidence in its classification (e.g., `0.90` for LOGIC, `0.60` for DRIFT).
* **Supporting Evidence:** Attached DOM snapshots, screenshots, filtered server logs.

### 6.4 `Execution_Memory_Update`
* **Purpose:** Pushes runtime insights into long-term memory to inform future executions.
* **Conceptual Schema:** 
  `{ "test_id", "duration_ms", "flaky_flag_raised", "retry_count" }`
* **Producer:** Execution Agent
* **Consumer:** Shared Memory / RAG DB
* **Confidence Score:** `1.0`
* **Supporting Evidence:** System clock measurements, retry logs.

---

## 7. Memory Architecture
* **Short-Term Memory:** Tracks the active execution queue, current runner load, and tests completed in the current run session.
* **Execution Memory (Shared State):** The `QAuraState` dictionary is updated in real-time with anomaly reports and coverage scores for downstream consumption.
* **Historical Memory (Vector DB):** Retains performance metrics, flakiness patterns, and historical failure classifications across multiple CI/CD runs.

---

## 8. Success Metrics
The success of the Execution Agent is measured by:
1. **Intelligent Prioritization Quality:** How quickly the system identifies critical path failures (Time-to-First-Failure).
2. **Execution Efficiency:** Reduction in overall test duration by avoiding redundant, blocked, or low-value tests.
3. **Anomaly Classification Accuracy:** The precision with which it accurately tags infrastructure vs. application issues, reducing noise for the Defect Intelligence Agent.
4. **Meaningful Coverage Gained:** Success is based on raising the *Coverage Confidence Score* rather than blindly executing raw lines of code.
5. **Output Usefulness:** The degree to which the `Structured_Anomaly_Report` accelerates the Phase 4 Defect Agent's root cause analysis without requiring log re-parsing.
