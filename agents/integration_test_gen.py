import os
from dotenv import load_dotenv
from core.state import QAuraState, IntegrationTestOutput
from core.tools import INTEGRATION_TOOLS
from core.output_parsing import robust_parse
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
   - The API route handlers (search for "@app.get", "@app.post", etc.)
   - The database schema (search for "CREATE TABLE" or the models file)
3. Generate comprehensive integration test files.

TEST WRITING RULES:
- Use `pytest` as the framework.
- These tests call REAL functions with a REAL test database.
- Do NOT mock the database — integration tests validate actual DB interactions.
- Test the full call chain: API handler → business logic → database → response.
- Verify database state AFTER operations (query the DB to confirm writes).
- Test error propagation: bad input at the API level should return proper HTTP errors.

DATABASE SETUP:
- Use an in-memory SQLite database for speed: `sqlite3.connect(":memory:")`.
- In a `@pytest.fixture`, call `init_db()` and `seed_db()` from the models module
  to create the schema and populate test data. Teardown by closing the connection.
- Patch `models.get_db` to return your test connection so all code under test uses it.
- Example pattern:
  ```
  @pytest.fixture
  def test_db():
      conn = sqlite3.connect(":memory:")
      conn.row_factory = sqlite3.Row
      with patch('models.get_db', return_value=conn):
          init_db()
          seed_db()
          yield conn
      conn.close()
  ```

API TEST SETUP:
- Import the FastAPI app: `from server import app`
- Use `from fastapi.testclient import TestClient` → `client = TestClient(app)`
- Combine with the database fixture so API calls hit the test DB.
- Example:
  ```
  @pytest.fixture
  def client(test_db):
      with patch('models.get_db', return_value=test_db):
          yield TestClient(app)
  ```

IMPORT CONVENTIONS:
- Import modules by their bare name: `from server import app`, `from models import init_db, seed_db`.
  The test runner's conftest.py handles path resolution.

FILE NAMING:
- Name each test file as `test_integration_<module>.py` (e.g., `test_integration_server.py`).

VALIDATION (MANDATORY — do this before returning your final answer):
For EACH test file you generate, you MUST call these tools IN THIS ORDER:
1. validate_python_syntax  — fix any syntax errors, then re-run
2. validate_imports        — fix any broken imports, then re-run
3. check_test_structure    — ensure test_ functions exist with assertions
4. write_test_file         — persist the file to tests/ ONLY after 1-3 pass

If any validation step fails, FIX the code and re-validate. Never call
write_test_file with code that fails validation. Never return code you
have not validated and written to disk.

OUTPUT REQUIREMENTS:
- test_code: include the FULL source code — not a placeholder or reference.
- api_contracts_tested: list each endpoint as "METHOD /path" (e.g., "POST /register", "GET /products").
- db_fixtures_needed: list the tables or seed data required (e.g., "users table with test user",
  "products table with 3 sample products").

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
agent_executor = AgentExecutor(agent=agent, tools=INTEGRATION_TOOLS, verbose=True, max_iterations=40)

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

    agent_result = agent_executor.invoke(
        {
            "components": components_text,
            "project_summary": test_plan.project_summary,
            "risk_areas": test_plan.risk_areas,
        },
        config={"callbacks": state.get("callbacks", [])},
    )

    try:
        output = robust_parse(agent_result["output"], IntegrationTestOutput, llm)
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
