import os
from dotenv import load_dotenv
from core.state import QAuraState, IntegrationTestOutput
from core.tools import INTEGRATION_TOOLS
# from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('INTEGRATION_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('INTEGRATION_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('INTEGRATION_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Integration Test Generator.

Your job is to generate integration tests using **pytest** that validate the
interactions between modules — API endpoints, database state changes, and
cross-function data flow.

WORKFLOW:
1. You will receive the test plan with components in integration_scope.
2. For EACH component, use the `search_codebase` tool to retrieve:
   - The function implementations
   - The API route handlers
   - The database schema
3. Generate comprehensive integration test files.

TEST WRITING RULES:
- Use `pytest` as the framework.
- These tests call REAL functions with a REAL test database 
- Do NOT mock the database — integration tests validate actual DB interactions.
- Test the full call chain: API handler → business logic → database → response.
- For API tests, use `fastapi.testclient.TestClient` to make actual HTTP requests.
- Verify database state AFTER operations (query the DB to confirm writes).
- Test error propagation: bad input at the API level should return proper HTTP errors.
- Include setup/teardown to create a fresh DB for each test.

VALIDATION (MANDATORY — do this before returning your final answer):
For EACH test file you generate, you MUST call these tools IN THIS ORDER:
1. validate_python_syntax  — fix any syntax errors, then re-run
2. validate_imports        — fix any broken imports, then re-run
3. check_test_structure    — ensure test_ functions exist with assertions
4. write_test_file         — persist the file to tests/ ONLY after 1-3 pass

If any validation step fails, FIX the code and re-validate. Never call
write_test_file with code that fails validation. Never return code you
have not validated and written to disk.

{format_instructions}
"""

HUMAN_PROMPT= """Based on the test plan, please generate integration tests for the following components:

{components}

Project summary: {project_summary}
Risk areas: {risk_areas}
"""

llm = ChatOpenAI(
    base_url=API_ENDPOINT,
    api_key=API_KEY,    
    model=API_MODEL,
    temperature=0.2
)

parser = PydanticOutputParser(pydantic_object=IntegrationTestOutput)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])
prompt = prompt.partial(format_instructions=parser.get_format_instructions())

agent = create_tool_calling_agent(llm, INTEGRATION_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=INTEGRATION_TOOLS, verbose=True, max_iterations=100)

def integration_gen_node(state: QAuraState) -> dict:
    """LangGraph node — generates integration tests for components in integration_scope."""
    print("--- Running Integration Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    integration_components = [
        c for c in test_plan.components if c.name in test_plan.integration_scope
    ]
    if not integration_components:
        return {"messages": ["No integration components found."]}
        
    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in integration_components
    )

    agent_result = agent_executor.invoke({
        "components": components_text,
        "project_summary": test_plan.project_summary,
        "risk_areas": test_plan.risk_areas
    })  

    try:
        # output = robust_parse(agent_result["output"], IntegrationTestOutput, llm)
        output = parser.invoke(agent_result["output"])
        tests = output.tests
        contracts = output.api_contracts_tested
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []
        contracts = []

    return {
        "integration_tests": tests,
        "messages": [
            f"Integration Generator produced {len(tests)} test files. "
            f"API contracts tested: {', '.join(contracts) if contracts else 'None'}"
        ]
    }
