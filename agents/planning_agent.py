import os
from dotenv import load_dotenv
from core.tools import PLANNING_TOOLS
from core.state import QAuraState, TestPlan
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langgraph.types import interrupt

load_dotenv()
API_KEY = os.environ.get('PLANNING_API_KEY', '')
API_ENDPOINT = os.environ.get('PLANNING_ENDPOINT', '')
API_MODEL = os.environ.get('PLANNING_MODEL_ID', '')


SYSTEM_PROMPT = """You are the QAura Test Architect.
Your job is to read the project requirements and produce a structured test plan that
downstream generators (Unit, Integration, E2E) will consume.

WORKFLOW:
1. Call `read_requirements_file` with the path provided by the user. Do NOT skip this step.
2. Identify every testable component from the requirements document.
3. For EACH component, determine:
   - file_path: the source file from the 'Source Files Under Test' section.
   - testing_type: the PRIMARY test category (Unit, Integration, or E2E).
     * Unit — pure logic, calculations, validators, anything testable in isolation.
     * Integration — API routes, DB interactions, cross-module data flow.
     * E2E — browser-driven user journeys through the frontend.
   - risk_level:
     * High — explicitly listed in 'Known Risk Areas' or involves auth/security/money.
     * Medium — complex logic or multiple dependencies but not a known risk.
     * Low — simple CRUD, static pages, trivial getters.
4. Populate the scope lists:
   - unit_scope: names of components whose testing_type is 'Unit'.
   - integration_scope: names of components whose testing_type is 'Integration'.
   - e2e_scope: names of components whose testing_type is 'E2E'.
   CRITICAL: every name in unit_scope / integration_scope / e2e_scope MUST exactly
   match a `name` field in the components list. No mismatches allowed.
5. List risk_areas — extract directly from the 'Known Risk Areas' section of the requirements.

QUALITY RULES:
- Aim for 5-10 components. Too few = gaps in coverage; too many = redundant splitting.
- Each component should map to at most one source file. If a file has multiple concerns
  (e.g., auth + session), split into separate components.
- The project_summary should be 1-2 sentences capturing what the app does.

{format_instructions}
"""

HUMAN_PROMPT = """Analyze the requirements located at: {path} and create a comprehensive test plan."""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

prompt = prompt.partial(format_instructions=PydanticOutputParser(pydantic_object=TestPlan).get_format_instructions())

llm = ChatOpenAI(
    base_url=API_ENDPOINT, 
    api_key=API_KEY, 
    model=API_MODEL, 
    temperature=0 
)

agent = create_tool_calling_agent(llm, PLANNING_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=PLANNING_TOOLS, verbose=True)

def test_architect_node(state: QAuraState) -> dict:
    """LangGraph node for Phase 1."""
    print("--- Running Test Architect ---")
    callbacks = state.get("callbacks", [])
    agent_result = agent_executor.invoke(
        {"path": state["requirements_path"]},
        config={"callbacks": callbacks},
    )

    try:
        generated_plan = robust_parse(agent_result["output"], TestPlan, llm)
        num_components = len(generated_plan.components)
    except Exception as e:
        print(f"Error parsing JSON: {e}\nAgent Output was: {agent_result['output'][:500]}")
        generated_plan = None
        num_components = 0
        
    return {
        "test_plan": generated_plan,
        "messages": [f"Architect generated a test plan with {num_components} components."]
    }

def hitl_approval_node(state: QAuraState) -> dict: 
    """Pauses execution for human review."""
    print("--- HITL Gate: Awaiting Approval ---")
    
    test_plan = state.get("test_plan")
    human_response = interrupt({
        "message": "Please review the test plan.",
        "plan_details": test_plan.model_dump() if test_plan else None
    })
    approved = human_response.get("approved", False)
    return {
        "plan_approved": approved,
        "messages": [f"Human approval status: {approved}"]
    }
