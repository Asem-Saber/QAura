import os
from dotenv import load_dotenv
from core.state import QAuraState, UnitTestOutput
from core.tools import UNIT_TOOLS
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('UNIT_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('UNIT_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('UNIT_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Unit Test Generator.

Your job is to generate isolated, mock-heavy unit tests using **pytest** for the
components listed in the unit_scope of the test plan.

WORKFLOW:
1. You will receive the test plan with components in unit_scope.
2. For EACH component, use the `search_codebase` tool to retrieve the actual
   source code — functions, classes, and their signatures.
3. Generate comprehensive pytest test files for each component.

TEST WRITING RULES:
- Use `pytest` as the framework. Import `pytest` and `unittest.mock` (Mock, patch, MagicMock).
- Mock ALL external dependencies: database calls, file I/O, network requests.
- Use descriptive test names following the pattern: test_<function>_<scenario>_<expected>.
- Every test must have at least one `assert` statement.
- Test these scenarios for each function:
  * Happy path (valid inputs → expected output)
  * Edge cases (empty strings, zero, None, boundary values)
  * Error paths (invalid input → expected exception or error return)
- Use `@pytest.fixture` for reusable setup.
- Use `@pytest.mark.parametrize` when testing multiple similar inputs.
- Do NOT import or connect to a real database. Mock `sqlite3.connect` and cursors.

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

HUMAN_PROMPT= """Based on the test plan, please generate unit tests for the following components:

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


parser = PydanticOutputParser(pydantic_object=UnitTestOutput)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])
prompt = prompt.partial(format_instructions=parser.get_format_instructions())

agent = create_tool_calling_agent(llm, UNIT_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=UNIT_TOOLS, verbose=True, max_iterations=40)

def unit_test_gen_node(state: QAuraState) -> dict:
    """LangGraph node — generates unit tests for components in unit_scope."""
    print("--- Running Unit Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    unit_components = [
        c for c in test_plan.components if c.name in test_plan.unit_scope
    ]
    if not unit_components:
        return {"messages": ["No unit components found."]}
        
    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in unit_components
    )

    agent_result = agent_executor.invoke({
        "components": components_text,
        "project_summary": test_plan.project_summary,
        "risk_areas": test_plan.risk_areas
    })

    try:
        output = robust_parse(agent_result["output"], UnitTestOutput, llm)
        tests = output.tests
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []

    return {
        "unit_tests": tests,
        "messages": [f"Unit Test Generator produced {len(tests)} test files."]
    }
