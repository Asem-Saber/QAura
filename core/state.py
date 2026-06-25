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
    file_name: str = Field(description="Name of the test file, e.g. test_auth_login.py")
    test_code: str = Field(description="Complete, runnable test source code")
    framework: str = Field(description="Testing framework used (pytest, jest, etc.)")
    target_component: str = Field(description="Name of the component this test covers, matching the test plan")
    test_type: Literal['unit', 'integration', 'e2e'] = Field(description="'unit', 'integration', or 'e2e'")

class UnitTestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated unit test files")
    coverage_notes: str = Field(description="Notes on what is and isn't covered")

class IntegrationTestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated integration test files")
    api_contracts_tested: List[str] = Field(description="API endpoints covered")
    db_fixtures_needed: list[str] = Field(description="Database fixtures required for these tests")

class E2ETestOutput(BaseModel):
    tests: List[GeneratedTest] = Field(description="List of generated E2E test files")
    user_flows_covered: list[str] = Field(description="User flows automated in E2E tests")

class ExecutionResultsSummary(BaseModel):
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    execution_duration_ms: int = 0
    critical_path_success: bool = True

class ComponentScore(BaseModel):
    component: str
    score: float

class CoverageConfidenceAssessment(BaseModel):
    overall_confidence: float = 0.0
    component_scores: List[ComponentScore] = Field(default_factory=list)
    identified_gaps: List[str] = Field(default_factory=list)

class StructuredAnomalyReport(BaseModel):
    anomaly_id: str
    test_id: str
    affected_component: str
    classification: Literal['INFRASTRUCTURE', 'APPLICATION_DEFECT', 'TEST_SCRIPT_DECAY']
    root_cause_hypothesis: str
    correlated_stack_trace: str

class ExecutionMemoryUpdate(BaseModel):
    test_id: str
    duration_ms: int
    flaky_flag_raised: bool
    retry_count: int

class QAuraState(TypedDict):
    requirements_path: str
    test_plan: TestPlan | None
    plan_approved: bool
    messages: Annotated[list, operator.add]
    unit_tests: list[GeneratedTest]
    integration_tests: list[GeneratedTest]
    e2e_tests: list[GeneratedTest]
    environment_status: dict
    execution_summary: ExecutionResultsSummary | None
    coverage_assessment: CoverageConfidenceAssessment | None
    anomaly_reports: list[StructuredAnomalyReport]
    execution_memory: list[ExecutionMemoryUpdate]
