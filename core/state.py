from typing import TypedDict, Annotated, List, Literal
from pydantic import BaseModel, Field
import operator

class TestComponent(BaseModel): 
    """A single component targeted for testing."""
    name: str = Field(description="Name of the component or module to test")
    file_path: str = Field(description="Relative path to the source file (e.g. demo_app/auth.py)")
    testing_type: Literal['Unit', 'Integration', 'E2E'] = Field(description="Unit, Integration, or E2E")
    risk_level: Literal['High', 'Medium', 'Low'] = Field(description="High, Medium, or Low")
    description: str = Field(description="Brief description of what to test")

class TestPlan(BaseModel):
    """Structured test plan produced by the Test Architect Agent."""
    project_summary: str = Field(description="Brief summary of the project under test")
    components: List[TestComponent] = Field(description="List of components to test with their scope")
    unit_scope: List[str] = Field(description="List of components needing unit tests")
    integration_scope: List[str] = Field(description="List of components needing integration tests")
    e2e_scope: List[str] = Field(description="List of components needing E2E/security tests")
    risk_areas: List[str] = Field(description="Identified high-risk areas from the requirements requiring extra attention")

class GeneratedTest(BaseModel):
    """A single generated test file."""
    file_name: str = Field(description="Name of the test file (e.g. test_auth.py, test_integration_server.py, test_e2e_login.py)")
    test_code: str = Field(description="Complete, runnable test source code — not a placeholder or reference")
    framework: str = Field(description="Testing framework used (pytest, jest, etc.)")
    target_component: str = Field(description="Name of the component this test covers, must match a name from the test plan")
    test_type: Literal['unit', 'integration', 'e2e'] = Field(description="'unit', 'integration', or 'e2e'")

class UnitTestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated unit test files")
    coverage_notes: str = Field(description="What IS covered and any scenarios intentionally skipped")

class IntegrationTestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated integration test files")
    api_contracts_tested: List[str] = Field(description="API endpoints covered as 'METHOD /path' (e.g. 'POST /register', 'GET /products')")
    db_fixtures_needed: List[str] = Field(description="Tables or seed data required (e.g. 'users table with test user')")

class E2ETestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated E2E test files")
    user_flows_covered: List[str] = Field(description="Short descriptions of each user flow tested (e.g. 'User registration with valid input')")

class ExecutionResultsSummary(BaseModel):
    total_tests: int = Field(default=0, description="Total number of tests from pytest summary")
    passed: int = Field(default=0, description="Number of tests that passed")
    failed: int = Field(default=0, description="Number of tests that failed (AssertionError, etc.)")
    blocked: int = Field(default=0, description="Number of tests that errored during collection or were skipped due to infra issues")
    execution_duration_ms: int = Field(default=0, description="Total execution time in milliseconds, extracted from pytest output")
    critical_path_success: bool = Field(default=True, description="TRUE if all High-risk components have >50% pass rate")

class ComponentScore(BaseModel):
    component: str
    score: float

class CoverageConfidenceAssessment(BaseModel):
    overall_confidence: float = Field(default=0.0, description="passed / total_tests as a float 0.0-1.0")
    component_scores: List[ComponentScore] = Field(default_factory=list, description="Per-component pass rate")
    identified_gaps: List[str] = Field(default_factory=list, description="Components with no tests or all tests blocked")

class StructuredAnomalyReport(BaseModel):
    anomaly_id: str = Field(description="Sequential ID like 'ANOM-001', 'ANOM-002'")
    test_id: str = Field(description="Path to the test file that triggered this anomaly")
    affected_component: str = Field(description="Name of the component affected")
    classification: Literal['INFRASTRUCTURE', 'APPLICATION_DEFECT', 'TEST_SCRIPT_DECAY'] = Field(description="Category of the failure")
    root_cause_hypothesis: str = Field(description="Brief explanation of the likely root cause")
    correlated_stack_trace: str = Field(description="Relevant error message or stack trace excerpt")

class ExecutionMemoryUpdate(BaseModel):
    test_id: str = Field(description="Path to the test file (e.g. 'tests/test_auth.py')")
    duration_ms: int = Field(description="Execution time for this test file in milliseconds")
    flaky_flag_raised: bool = Field(default=False, description="Always false for single-run execution")
    retry_count: int = Field(default=0, description="Always 0 — no retry configured")

class ExecutionOutput(BaseModel):
    """Combined output from the Execution Agent."""
    execution_summary: ExecutionResultsSummary
    coverage_assessment: CoverageConfidenceAssessment
    anomaly_reports: List[StructuredAnomalyReport]
    execution_memory: List[ExecutionMemoryUpdate]

class DefectAnalysis(BaseModel):
    """Root-cause analysis for a single anomaly produced by the Defect Intelligence Agent."""
    anomaly_id: str = Field(description="Matches StructuredAnomalyReport.anomaly_id, e.g. 'ANOM-001'")
    confirmed_root_cause: str = Field(description="Confirmed root cause after RAG + log search")
    resolution_action: Literal[
        'NO_ACTION',
        'SELF_HEAL_LOCATOR',
        'SELF_HEAL_LOGIC',
        'ESCALATE_HUMAN',
    ] = Field(
        description=(
            "NO_ACTION: transient/false flag. "
            "SELF_HEAL_LOCATOR: stale selector in the test. "
            "SELF_HEAL_LOGIC: application code bug, needs a fix PR. "
            "ESCALATE_HUMAN: systemic/complex, needs an engineer."
        )
    )
    evidence: str = Field(description="Log excerpts, RAG hits, or stack traces supporting the analysis")
    recommended_fix: str = Field(description="Plain-English description of the recommended corrective action")

class DefectIntelligenceOutput(BaseModel):
    """Wrapper returned by the Defect Intelligence Agent."""
    analyses: List[DefectAnalysis] = Field(description="One DefectAnalysis per anomaly investigated")

class HealingAction(BaseModel):
    """A single corrective action taken by the Self-Healing Agent."""
    anomaly_id: str = Field(description="Matches DefectAnalysis.anomaly_id")
    action_type: Literal[
        'NO_ACTION',
        'SELF_HEAL_LOCATOR',
        'SELF_HEAL_LOGIC',
        'ESCALATE_HUMAN',
    ] = Field(description="Resolution action taken")
    target_file: str = Field(description="Relative path to the file that was modified (or '' if no file change)")
    original_code: str = Field(default="", description="The original code snippet that was replaced")
    patched_code: str = Field(default="", description="The new code snippet written to the file")
    explanation: str = Field(description="Plain-English explanation of what was done and why")
    success: bool = Field(default=True, description="Whether the patch was applied without errors")

class SelfHealingOutput(BaseModel):
    """Wrapper returned by the Self-Healing Agent."""
    actions: List[HealingAction] = Field(description="One HealingAction per DefectAnalysis processed")
    loop_decision: Literal[
        'RE_EXECUTE',
        'RE_PLAN',
        'ESCALATE',
        'DONE',
    ] = Field(description=(
        "RE_EXECUTE: test was fixed, re-run tests. "
        "RE_PLAN: app code was fixed, re-evaluate. "
        "ESCALATE: needs human intervention. "
        "DONE: nothing to heal."
    ))
    escalation_summary: str = Field(default="", description="Human-readable summary if escalation is needed")

class QAReportSection(BaseModel):
    """A single titled section inside the QA report."""
    title: str = Field(description="Section heading, e.g. 'Execution Metrics'")
    content: str = Field(description="Markdown-formatted body text for this section")

class QAReport(BaseModel):
    """Final human-readable QA report compiled by the Reporting Agent."""
    run_id: str = Field(description="Thread ID for this pipeline run, e.g. 'qaura_run_1'")
    generated_at: str = Field(description="ISO 8601 UTC timestamp")
    executive_summary: str = Field(description="2-3 sentence plain-English summary of the run")
    sections: List[QAReportSection] = Field(description="Ordered report sections")
    overall_verdict: Literal['PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'BLOCKED'] = Field(
        description=(
            "PASS: all tests pass. "
            "PASS_WITH_WARNINGS: some failures but critical path ok. "
            "FAIL: critical path broken. "
            "BLOCKED: infra unreachable, no tests ran."
        )
    )

class QAuraState(TypedDict):
    requirements_path: str
    test_plan: TestPlan | None
    plan_approved: bool
    messages: Annotated[list, operator.add]
    unit_tests: Annotated[List[GeneratedTest], operator.add]
    integration_tests: Annotated[List[GeneratedTest], operator.add]
    e2e_tests: Annotated[List[GeneratedTest], operator.add]
    environment_status: dict
    execution_summary: ExecutionResultsSummary | None
    coverage_assessment: CoverageConfidenceAssessment | None
    anomaly_reports: Annotated[List[StructuredAnomalyReport], operator.add]
    execution_memory: Annotated[List[ExecutionMemoryUpdate], operator.add]
    qa_report: QAReport | None
    report_path: str
    defect_analyses: Annotated[List[DefectAnalysis], operator.add]
    healing_actions: Annotated[List[HealingAction], operator.add]
    loop_decision: str
    healing_iterations: int
    plan_revision_count: int
