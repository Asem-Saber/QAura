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

class QAuraState(TypedDict):
    requirements_path: str
    test_plan: TestPlan | None
    plan_approved: bool
    messages: Annotated[list, operator.add]