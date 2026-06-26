import os
from dotenv import load_dotenv
from core.state import QAuraState, UnitTestOutput
from core.tools import UNIT_TOOLS
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableConfig
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('UNIT_TEST_API_KEY', '')
API_ENDPOINT = os.environ.get('UNIT_TEST_ENDPOINT', '')
API_MODEL = os.environ.get('UNIT_TEST_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura Unit Test Generator.

Your job is to generate isolated, mock-heavy unit tests using **pytest** for the
components listed in the test plan.

MANDATORY WORKFLOW — you MUST follow these steps IN ORDER for EACH component.
Skipping any step is a failure. Do NOT return your final answer until every
component has been through ALL steps.

STEP 1 — RETRIEVE SOURCE CODE
  Call `search_codebase` for each component to get the actual implementation:
  functions, classes, signatures, dependencies, and how they interact.
  Read the code carefully — your tests must match the real API.

STEP 2 — GENERATE TESTS
  Write a complete pytest test file for the component (rules below).

STEP 3 — VALIDATE (loop until clean)
  Call these tools in order. If ANY fails, fix the code and re-run from 3a:
    3a. `validate_python_syntax`  → fix syntax errors
    3b. `validate_imports`        → fix broken imports
    3c. `check_test_structure`    → ensure test_ functions with assertions

STEP 4 — WRITE TO DISK
  Call `write_test_file` with the validated code. This is NON-OPTIONAL.
  You have NOT completed a component until write_test_file succeeds.
  Do NOT move to the next component until the current one is written.

STEP 5 — FINAL OUTPUT
  Only after ALL components are validated and written, return your structured
  output. The `test_code` field must contain the FULL source code you wrote —
  not a placeholder or summary.

TEST WRITING RULES

Framework & Style:
- Use `pytest` with `unittest.mock` (Mock, patch, MagicMock).
- Descriptive names: `test_<function>_<scenario>_<expected>`.
- Every test MUST have at least one `assert`.
- Use `@pytest.fixture` for reusable setup.
- Use `@pytest.mark.parametrize` for multiple similar inputs.

Isolation:
- Mock ALL external dependencies: databases, file I/O, network calls, third-party services.
- Patch at the call site (where the dependency is looked up in the module under test).
- Never connect to real infrastructure in a unit test.

Coverage per function:
- Happy path (valid inputs → expected output)
- Edge cases (empty inputs, zero, None, boundary values)
- Error paths (invalid input → expected exception or error return)

Import conventions:
- Study the source code retrieved in Step 1 to determine the correct import paths.
- Import the module under test using the path that matches the project structure.

File naming:
- `test_<module>.py` — one test file per component.

{format_instructions}
"""

HUMAN_PROMPT = """Generate unit tests for the following components. For EACH one, you MUST:
1. Call search_codebase to read its source code
2. Write tests based on the real implementation
3. Validate with validate_python_syntax, validate_imports, check_test_structure
4. Call write_test_file to save to disk
Do NOT return your final answer until every component has been written to disk.

Components to test:
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

def unit_test_gen_node(state: QAuraState, config: RunnableConfig | None = None) -> dict:
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

    callbacks = (config or {}).get("callbacks", [])
    agent_result = agent_executor.invoke(
        {
            "components": components_text,
            "project_summary": test_plan.project_summary,
            "risk_areas": test_plan.risk_areas,
        },
        config={"callbacks": callbacks},
    )

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
