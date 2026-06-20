import os 
import json
from dotenv import load_dotenv
from typing import TypedDict, Annotated, List, Optional
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

# Setup configuration 
load_dotenv()
API_KEY = os.environ['GITHUB_API_KEY']
API_ENDPOINT = os.environ['GITHUB_ENDPOINT']
API_MODEL = os.environ['GITHUB_MODEL_ID']

# define Schema 
class TestComponent(BaseModel): 
    name: str = Field(description="Name of the component or feature (e.g., 'Authentication')")
    testing_type: str = Field(description="Unit, Integration, or E2E")
    description: str = Field(description="What needs to be tested")
    risk_level: str = Field(description="High, Medium, or Low")

class TestPlan(BaseModel):
    components: List[TestComponent]
    priority_notes: str

class QAuraState(TypedDict):
    requirements_path: str         
    test_plan: TestPlan | None     
    plan_approved: bool            
    messages: Annotated[list, "add_messages"] 


# define tools 
@tool 
def read_requirements_file(file_path: str) -> str: 
    """Read the project requirements markdown file to understand the scope of testing. 
    
    Args: 
        file_path: The path to the requirements file (e.g., 'project_requirements.md') 
    """ 
    try: 
        with open(file_path, 'r', encoding='utf-8') as f: 
            return f.read() 
    except Exception as e: 
        return f"Error reading file: {e}" 

PLANNING_TOOLS = [read_requirements_file]

# define the Architect Agent 
SYSTEM_PROMPT = """You are the QAura Test Architect. 
Your job is to read the project requirements and draft a comprehensive test plan.
Use your tools to read the requirements file provided by the user.

Guidelines:
- Cover Unit, Integration, and E2E testing.
- Pay special attention to the "Known Risk Areas" mentioned in the requirements.
- Prioritize high-risk components (like Authentication).
"""

llm= ChatOpenAI(
    base_url= API_ENDPOINT, 
    api_key = API_KEY, 
    model = API_MODEL, 
    temperature = 0 
)
llm_with_tools = llm.bind_tools(PLANNING_TOOLS)

llm_structured = llm_with_tools.with_structured_output(TestPlan)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Please create a test plan based on the requirements located at: {filepath}"),
])

architect_chain = prompt | llm_structured

# define the Architect Node 
def test_architect_node(state: QAuraState) -> dict: 
    """LangGraph node for Phase 1."""
    print("--- Running Test Architect ---")
    generated_plan = architect_chain.invoke({"filepath": state["requirements_path"]})
    
    return {
        "test_plan": generated_plan,
        "messages": [f"Architect generated a test plan with {len(generated_plan.components)} components."]
    }

# define the HITL Node 
def hitl_approval_node(state: QAuraState) -> dict: 
    """Pauses execution for human review."""
    print("--- HITL Gate: Awaiting Approval ---")
    
    test_plan = state.get("test_plan")
    human_response = interrupt({
        "message": "Please review the test plan.",
        "plan_details": test_plan.dict() if test_plan else None
    })
    approved = human_response.get("approved", False)
    return {
        "plan_approved": approved,
        "messages": [f"Human approval status: {approved}"]
    }

# define the graph builder 
builder = StateGraph(QAuraState)

# Add Nodes 
builder.add_node("test_architect", test_architect_node) 
builder.add_node("human_approval", hitl_approval_node) 

# Add Edges 
builder.add_edge(START, "test_architect") 
builder.add_edge("test_architect", "human_approval") 
builder.add_edge("human_approval", END) 

# Initialize memory
memory = MemorySaver()

# compile the graph
graph = builder.compile(checkpointer=memory)


# define the main runner
if __name__ == "__main__": 
    print("Starting QAura Planning Agent...")
    config = {"configurable": {"thread_id": "test_plan_thread_1"}}  
    
    events = graph.stream({"requirements_path": "project_requirements.md"}, config=config, stream_mode="values")
    
    for output in events:
        print("Current State:", output)
    
    print("\n--- Graph Paused ---")
    print("Waiting for human input...")
    
    human_input = input("Approve the test plan? (y/n): ")
    is_approved = human_input.lower() == 'y'

    print("\n--- Resuming Graph ---")
    resume_events = graph.stream(
        Command(resume={"approved": is_approved}), 
        config=config, 
        stream_mode="values"
    )

    final_state = None
    for output in resume_events:
        final_state = output
    print("\n--- Final Output ---")
    print(f"Plan Approved: {final_state.get('plan_approved')}")

    print("\n--- Writing Output to File ---")
    with open("test_plan.json", "w") as f:
        json.dump(final_state.get("test_plan").model_dump() if final_state.get("test_plan") else {}, f, indent=2)

    print("Output written to test_plan.json")