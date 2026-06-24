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
API_KEY = os.environ.get('GITHUB_API_KEY', '')
API_ENDPOINT = os.environ.get('GITHUB_ENDPOINT', '')
API_MODEL = os.environ.get('GITHUB_MODEL_ID', '')

# quick note : planning agent might need 'list_directories" tool 

SYSTEM_PROMPT = """You are the QAura Test Architect. 
Your job is to read the project requirements and draft a comprehensive test plan.
You MUST use the `read_requirements_file` tool to read the requirements file provided by the user before drafting the plan.

Guidelines:
- Map each functional requirement to a specific component.
- Extract the 'file_path' for each component based on the 'Source Files Under Test' section.
- Categorize components into 'Unit', 'Integration', or 'E2E' for the testing_type.
- Accurately capture the 'Known Risk Areas' to assign a risk_level of 'High', 'Medium', or 'Low'.

{format_instructions}
"""

HUMAN_PROMPT = """Analyze the requirements located at: {path} and create a comprehensive test plan."""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

parser = PydanticOutputParser(pydantic_object=TestPlan)
prompt = prompt.partial(format_instructions=parser.get_format_instructions())

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
    agent_result = agent_executor.invoke({
        "path": state["requirements_path"]
    })

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
