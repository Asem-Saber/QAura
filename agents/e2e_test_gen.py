import os
from dotenv import load_dotenv
from core.state import QAuraState, E2ETestOutput
from core.tools import E2E_TOOLS
from core.output_parsing import robust_parse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

load_dotenv()
API_KEY = os.environ.get('GITHUB_API_KEY', '')
API_ENDPOINT = os.environ.get('GITHUB_ENDPOINT', '')
API_MODEL = os.environ.get('GITHUB_MODEL_ID', '')

SYSTEM_PROMPT = """You are the QAura E2E Test Generator. Your job is to write \
end-to-end browser tests using Selenium WebDriver that exercise complete user \
journeys through the application under test.

You work on ANY application — do not assume a specific framework, set of pages,
URLs, or element names. Always discover the real structure of the app from the
codebase before writing tests.

WORKFLOW:
1. You will receive the test plan with the components in e2e_scope.
2. Use the `search_codebase` tool to discover, for each component:
   - The frontend templates / views to find forms, buttons, links, and the
     locator attributes they expose (prefer `data-testid`, else stable ids/names).
   - The route/controller handlers to understand what each page submits to and
     where successful actions navigate.
   - The authentication / session flow, if the journey requires being logged in.
   Run several targeted searches per component; never guess at element names,
   routes, or page paths — derive them from what `search_codebase` returns.
3. Generate comprehensive E2E test files covering the real user flows of the app.

TEST WRITING RULES:
- Use `selenium` WebDriver with `pytest`.
- Use `webdriver.Chrome(options)` with `--headless` for CI compatibility.
- Locate elements using `data-testid` attributes as the PRIMARY strategy when the
  app exposes them (`driver.find_element(By.CSS_SELECTOR, "[data-testid='...']")`);
  fall back to stable `id` or `name` attributes only when no test id exists.
- Use EXPLICIT waits only (`WebDriverWait` + `expected_conditions`). NEVER use
  `time.sleep()` or implicit waits.
- Structure each test as a complete user journey: navigate → interact → assert →
  cleanup.
- Include a `@pytest.fixture` for driver setup/teardown.
- Drive the app via its base URL. Read it from a `BASE_URL` constant (default it to
  the value documented in the codebase/requirements, or an env var) rather than
  hard-coding a host you assumed.

WHAT TO COVER:
Derive the flows from the components in e2e_scope and what you find in the codebase.
For each component, test the primary success path plus the meaningful failure paths
the UI is supposed to handle (e.g. invalid input shows an error, unauthenticated
access is redirected). Typical journeys include sign-in/sign-out, form submission
and its confirmation, navigation between pages, and any stateful action the UI
performs — but only those that actually exist in the app under test.

VALIDATION (MANDATORY — do this before returning your final answer):
For EACH test file you generate, you MUST call these tools IN THIS ORDER:
1. validate_python_syntax     — fix any syntax errors, then re-run
2. validate_imports           — fix any broken imports, then re-run
3. check_test_structure       — ensure test_ functions exist with assertions
4. validate_selenium_locators — ensure every locator matches the real templates
5. write_test_file            — persist to tests/ ONLY after 1-4 pass

If any validation step fails, FIX the code and re-validate. Never call
write_test_file with code that fails validation. Never return code you
have not validated and written to disk.

{format_instructions}
"""

HUMAN_PROMPT= """Based on the test plan, please generate E2E tests for the following components:

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

parser = PydanticOutputParser(pydantic_object=E2ETestOutput)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", HUMAN_PROMPT),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])
prompt = prompt.partial(format_instructions=parser.get_format_instructions())

agent = create_tool_calling_agent(llm, E2E_TOOLS, prompt)
agent_executor = AgentExecutor(agent=agent, tools=E2E_TOOLS, verbose=True, max_iterations=100)

def e2e_gen_node(state: QAuraState) -> dict:
    """LangGraph node — generates E2E tests for e2e_scope."""
    print("--- Running E2E Test Generator ---")
    test_plan = state.get("test_plan")
    if not test_plan:
        return {"messages": ["No test plan found."]}

    e2e_components = [
        c for c in test_plan.components if c.name in test_plan.e2e_scope
    ]
    if not e2e_components:
        return {"messages": ["No e2e components found."]}
        
    components_text = "\n".join(
        f"- {c.name} (file: {c.file_path}, risk: {c.risk_level}): {c.description}"
        for c in e2e_components
    )

    agent_result = agent_executor.invoke({
        "components": components_text,
        "project_summary": test_plan.project_summary,
        "risk_areas": test_plan.risk_areas
    })

    try:
        output = robust_parse(agent_result["output"], E2ETestOutput, llm)
        tests = output.tests
    except Exception as e:
        print(f"Error parsing output: {e}")
        tests = []

    return {
        "e2e_tests": tests,
        "messages": [f"E2E Generator produced {len(tests)} test files."]
    }

