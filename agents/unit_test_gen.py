# agents/unit_test_gen.py
"""Unit Test Generator agent — Phase 2 parallel branch.

Generates isolated, mock-heavy pytest tests from the test plan's
unit_scope. Runs in parallel with the Integration and E2E generators.
Each component in unit_scope gets its own GeneratedTest file.

Pipeline per component:
    1. Resolve module path → read source
    2. Parse AST → symbol inventory (fed to LLM)
    3. Discover collaborator seams → mock targets (fed to LLM)
    4. Lookup existing fixtures → avoid duplication (fed to LLM)
    5. Invoke LLM → structured GeneratedTest
    6. Validate syntax → retry on failure (up to max_retries)
    7. Verify coverage → flag uncovered symbols against AST
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser, OutputParserException
from langchain_core.prompts import ChatPromptTemplate

from config import CONFTEST_PATH, PROJECT_ROOT, get_llm
from core.state import (
    GeneratedTest,
    Phase,
    QAuraState,
    TestPlan,
    UnitScopeItem,
)
from core.tools import (
    discover_collaborators,
    lookup_existing_fixtures,
    parse_ast,
    read_source_file,
    resolve_module_path,
    validate_syntax,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """\
You are the Unit Test Generator for QAura, an autonomous testing pipeline. \
Your job is to generate isolated, mock-heavy pytest tests for a single \
component based on its source code and an AST-derived symbol inventory.

## What You Must Do

1. Generate a complete, self-contained pytest test file (with all imports).
2. Test every public symbol listed in the AST inventory.
3. Mock ALL external dependencies — no real database, network, file I/O, \
   time, or randomness.
4. For each public symbol, emit at minimum:
   - One happy-path test (normal valid input -> expected output)
   - Boundary tests (empty string, zero, max-length, off-by-one)
   - Null/missing tests (None, missing kwargs, empty collections)
   - Error-path tests (each documented or inferred exception)
5. Use pytest fixtures for setup. Prefer factory fixtures over rigid singletons.
6. Use @pytest.mark.parametrize when testing the same logic with varied inputs.

## What You Must Not Do

- Do NOT call datetime.now(), uuid.uuid4(), random.random() directly. \
  Inject all non-determinism through constructor params or fixtures.
- Do NOT mock deep internal call chains (e.g. \
  mock_db.query.return_value.filter.return_value.first.return_value). \
  Mock at collaborator boundaries instead.
- Do NOT over-specify mocks. Assert on outcomes and collaborator intent, \
  not on intermediate builder steps.
- Do NOT test private methods (those starting with _) except __init__.
- Do NOT generate integration tests. This is unit-level only.

## Naming Convention

Test functions: test_<function>_<scenario>_<expected>
Example: test_create_user_duplicate_email_raises_conflict

## Output Requirements

- Populate `covered_symbols` with every AST symbol your tests exercise.
- Populate `test_cases` with metadata for each test function.
- If shared fixtures would benefit other test files, put them in \
  `conftest_contribution` (just the @pytest.fixture functions, no imports).
- If a symbol cannot be tested, explain why in `coverage_notes`.
"""

USER_TEMPLATE = """\
## Project Summary
{project_summary}

## Target Component
- Component name: {component}
- Import module: {module}

## AST Symbol Inventory
{ast_inventory}

## Collaborator Seams (these must be mocked, not called for real)
{collaborators}

## Existing Fixtures (reuse these — do not redefine)
{existing_fixtures}

## Source Code Under Test
{source_code}

Generate a complete pytest test file for {component}. The file must be \
self-contained with all necessary imports. Return structured output \
matching the GeneratedTest schema.
"""

RETRY_TEMPLATE = """\
The test file you previously generated failed syntax validation.

## Syntax Error
{syntax_error}

## Original Generated Code
{test_code}

## Original Context (for reference)
- Component: {component}
- Module: {module}

## AST Symbol Inventory
{ast_inventory}

## Source Code Under Test
{source_code}

Fix the syntax error and return the corrected test file. Keep all test \
logic intact — only fix what is broken. If the error is in a fixture or \
import, fix that too. Return structured output matching the GeneratedTest \
schema with all fields populated as before.
"""
# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════
@dataclass
class GenerationConfig:
    """Tunable parameters for the generation pipeline.
    Attributes:
        llm: Chat model override. If None, auto-selected from env.
        project_root: Root for resolving dotted module paths.
        conftest_path: Path to conftest.py for fixture reuse lookup.
        max_retries: Max syntax-validation retries per file.
        skip_unvalidated: If True, drop files that fail validation
            after all retries. If False, include them with
            syntax_validated=False.
    """
    llm: BaseChatModel | None = None
    project_root: str = str(PROJECT_ROOT)
    conftest_path: str = str(CONFTEST_PATH)
    max_retries: int = 2
    skip_unvalidated: bool = False

# ═══════════════════════════════════════════════════════════════════════
# CHAIN BUILDERS
# ═══════════════════════════════════════════════════════════════════════
_OUTPUT_PARSER = PydanticOutputParser(pydantic_object=GeneratedTest)

def _build_generation_chain(llm: BaseChatModel):
    """Build the LCEL chain for initial test generation."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_TEMPLATE),
    ])
    return prompt | llm | _OUTPUT_PARSER

def _build_retry_chain(llm: BaseChatModel):
    """Build the LCEL chain for syntax-error retry attempts."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", RETRY_TEMPLATE),
    ])
    return prompt | llm | _OUTPUT_PARSER

# ═══════════════════════════════════════════════════════════════════════
# COVERAGE VERIFICATION
# ═══════════════════════════════════════════════════════════════════════
def _extract_public_symbols(source_code: str) -> List[str]:
    """Parse source code structurally and return all public testable symbol names.
    Scans only module-level statements to prevent extracting nested helper closures.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        logger.warning(
            "Source has syntax errors — cannot extract symbols for coverage verification"
        )
        return []

    symbols: List[str] = []

    # Iterate through module-level nodes only to isolate structural context
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if _is_public(node.name):
                symbols.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_public(child.name):
                        symbols.append(f"{node.name}.{child.name}")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(node.name):
                symbols.append(node.name)

    return symbols

def _is_public(name: str) -> bool:
    """Check if a symbol name is public (not private/dunder).
    __init__ is treated as public for constructor testing coverage.
    """
    if name.startswith("__") and name.endswith("__"):
        return name == "__init__"
    return not name.startswith("_")

def _verify_coverage(test: GeneratedTest, source_code: str) -> List[str]:
    """Cross-check the test's coverage claims against the actual AST symbols."""
    declared = set(_extract_public_symbols(source_code))
    covered = set(test.covered_symbols)
    tested = {tc.target_symbol for tc in test.test_cases}
    
    completely_missing = sorted(declared - covered)
    claimed_not_tested = sorted(covered - tested)
    
    gaps: List[str] = []
    if completely_missing:
        gaps.append(f"Uncovered symbols: {', '.join(completely_missing)}")
    if claimed_not_tested:
        gaps.append(f"Symbols in covered_symbols but no test case: {', '.join(claimed_not_tested)}")
        
    if not gaps:
        gaps.append("All public symbols have associated test cases.")
    return gaps

# ═══════════════════════════════════════════════════════════════════════
# LLM INVOCATION HELPER
# ═══════════════════════════════════════════════════════════════════════
def _invoke_chain(
    chain,
    context: dict,
    component: str,
    module: str,
    llm: BaseChatModel,
) -> GeneratedTest:
    """Invoke an LCEL generation pipeline and apply downstream metadata."""
    try:
        test = chain.invoke(context)
    except OutputParserException as e:
        logger.error("LLM output parsing failed for %s: %s", component, e)
        raise OutputParserException(
            f"Failed to parse LLM output for {component}: {e}"
        ) from e

    test.target_component = component
    test.target_module = module
    test.generator_model = _extract_model_name(llm)
    return test

# ═══════════════════════════════════════════════════════════════════════
# SYNTAX VALIDATION WITH RETRY
# ═══════════════════════════════════════════════════════════════════════
def _validate_and_retry(
    test: GeneratedTest,
    generation_chain,
    retry_chain,
    component: str,
    module: str,
    ast_inventory: str,
    source_code: str,
    max_retries: int,
    llm: BaseChatModel,
) -> GeneratedTest:
    """Validate generated code syntax; retry generation via retry_chain if invalid."""
    for attempt in range(max_retries + 1):
        result = validate_syntax.invoke({"code": test.test_code})

        if result == "VALID":
            test.syntax_validated = True
            if attempt == 0:
                logger.info("Syntax OK for %s (first try)", component)
            else:
                logger.info("Syntax OK for %s (after retry %d)", component, attempt)
            return test

        logger.warning(
            "Syntax validation failed for %s (attempt %d/%d): %s",
            component, attempt + 1, max_retries + 1, result,
        )

        if attempt >= max_retries:
            test.syntax_validated = False
            logger.error(
                "Syntax validation exhausted for %s after %d retries — emitting with syntax_validated=False",
                component, max_retries,
            )
            return test

        # Execute retry using pre-built optimized chain
        test = _invoke_chain(
            chain=retry_chain,
            context={
                "syntax_error": result,
                "test_code": test.test_code,
                "component": component,
                "module": module,
                "ast_inventory": ast_inventory,
                "source_code": source_code,
            },
            component=component,
            module=module,
            llm=llm,
        )

    test.syntax_validated = False
    return test

# ═══════════════════════════════════════════════════════════════════════
# PER-COMPONENT PIPELINE
# ═══════════════════════════════════════════════════════════════════════
def _generate_for_component(
    item: UnitScopeItem,
    project_summary: str,
    config: GenerationConfig,
) -> GeneratedTest:
    """Run the complete analytical and LLM generation pipeline for one component."""
    llm = config.llm or get_llm()
    
    # 1. Chain Pre-compilation Optimization
    generation_chain = _build_generation_chain(llm)
    retry_chain = _build_retry_chain(llm)

    # 2. Resolve and read source
    file_path = resolve_module_path.invoke(
        {"module": item.module, "project_root": config.project_root}
    )
    if file_path.startswith("ERROR"):
        raise FileNotFoundError(file_path)
    source_code = read_source_file.invoke({"file_path": file_path})
    logger.debug("Read source: %s (%d chars)", file_path, len(source_code))
    
    # 3. Component Boundary Discovery 
    ast_inventory = parse_ast.invoke({"source_code": source_code, "module_path": item.module})
    collaborators = discover_collaborators.invoke({"source_code": source_code, "module_path": item.module})
    existing_fixtures = lookup_existing_fixtures.invoke({"conftest_path": config.conftest_path})
    
    # 4. Invoke Generation Chain
    logger.info("Generating unit tests for %s (%s)", item.component, item.module)
    test = _invoke_chain(
        chain=generation_chain,
        context={
            "project_summary": project_summary,
            "component": item.component,
            "module": item.module,
            "ast_inventory": ast_inventory,
            "collaborators": collaborators,
            "existing_fixtures": existing_fixtures,
            "source_code": source_code,
        },
        component=item.component,
        module=item.module,
        llm=llm,
    )
    
    # 5. Syntax Validation Loop
    test = _validate_and_retry(
        test=test,
        generation_chain=generation_chain,
        retry_chain=retry_chain,
        component=item.component,
        module=item.module,
        ast_inventory=ast_inventory,
        source_code=source_code,
        max_retries=config.max_retries,
        llm=llm,
    )
    
    # 6. Post-generation Automated Audit
    coverage_gaps = _verify_coverage(test, source_code)
    existing_notes = test.coverage_notes.strip()
    gap_text = "\n".join(coverage_gaps)
    test.coverage_notes = f"{existing_notes}\n{gap_text}".strip() if existing_notes else gap_text
    
    return test

# ═══════════════════════════════════════════════════════════════════════
# NODE FUNCTION (LangGraph entry point)
# ═══════════════════════════════════════════════════════════════════════
def unit_test_gen_node(
    state: Dict[str, Any],
    config: GenerationConfig | None = None,
) -> Dict[str, Any]:
    """LangGraph node: generate unit tests for all components in unit_scope batching."""
    cfg = config or GenerationConfig()

    plan: TestPlan | None = state.get("test_plan")
    if plan is None or not plan.unit_scope:
        logger.info("No unit_scope in test plan — skipping unit test generation.")
        return {
            "unit_tests": [],
            "messages": ["Unit: no unit scope defined, skipped."],
            "current_phase": Phase.GENERATION,
        }

    total = len(plan.unit_scope)
    logger.info("Starting unit test generation: %d component(s)", total)

    generated: List[GeneratedTest] = []
    messages: List[str] = []

    for idx, item in enumerate(plan.unit_scope, start=1):
        logger.info("Component %d/%d: %s", idx, total, item.component)
        messages.append(f"Unit: starting {item.component} ({item.module})")

        try:
            test = _generate_for_component(
                item=item,
                project_summary=plan.project_summary,
                config=cfg,
            )

            if not test.syntax_validated and cfg.skip_unvalidated:
                messages.append(
                    f"Unit: SKIPPED {item.component} — failed syntax validation after {cfg.max_retries} retries"
                )
                continue

            generated.append(test)
            messages.append(_format_success_message(test, item.component))

        except FileNotFoundError as e:
            logger.error("Module not found for %s: %s", item.component, e)
            messages.append(f"Unit: FAILED {item.component} — module not found: {e}")
        except OutputParserException as e:
            logger.error("LLM output parsing failed for %s: %s", item.component, e)
            messages.append(f"Unit: FAILED {item.component} — LLM output error: {e}")
        except Exception as e:
            logger.exception("Unexpected failure for %s", item.component)
            messages.append(f"Unit: FAILED {item.component} — {type(e).__name__}: {e}")

    # Aggregating Execution Results Summary
    total_cases = sum(len(t.test_cases) for t in generated)
    validated = sum(1 for t in generated if t.syntax_validated)
    messages.append(
        f"Unit: generation complete — {len(generated)} file(s), {total_cases} test cases, {validated}/{len(generated)} validated"
    )

    return {
        "unit_tests": generated,
        "messages": messages,
        "current_phase": Phase.GENERATION,
    }

def _format_success_message(test: GeneratedTest, component: str) -> str:
    """Build a detailed progress message for a successful generation string."""
    status = "validated" if test.syntax_validated else "UNVALIDATED"
    msg = f"Unit: {component} -> {test.file_name} ({len(test.test_cases)} tests, {len(test.covered_symbols)} symbols, {status})"
    
    if test.coverage_notes and "Uncovered symbols:" in test.coverage_notes:
        for line in test.coverage_notes.split("\n"):
            if "Uncovered symbols:" in line:
                msg += f" | {line}"
                break
    return msg

# convenience_wrapper.py

class UnitTestGenerator:
    """Object-oriented wrapper around unit_test_gen_node.
    Useful for:
    Standalone execution without LangGraph
    Testing with a mock LLM
    Programmatic integration in other pipelines
    Example:
    >>> from config import get_llm
    >>> from core.state import TestPlan, UnitScopeItem
    >>> gen = UnitTestGenerator(project_root="./my_project")
    >>> plan = TestPlan(
    ... project_summary="Auth service",
    ... unit_scope=[
    ... UnitScopeItem("UserService", "auth.service")
    ... ],
    ... )
    >>> tests = gen.generate(plan)
    >>> len(tests)
    1
    """
    def __init__(
        self,
        llm: BaseChatModel | None = None,
        project_root: str | None = None,
        conftest_path: str | None = None,
        max_retries: int = 2,
        skip_unvalidated: bool = False,
    ) -> None:
        self._config = GenerationConfig(
            llm=llm,
            project_root=project_root or str(PROJECT_ROOT),
            conftest_path=conftest_path or str(CONFTEST_PATH),
            max_retries=max_retries,
            skip_unvalidated=skip_unvalidated,
        )

    @property
    def config(self) -> GenerationConfig:
        """Read-only access to the internal config."""
        return self._config

    def generate(self, test_plan: TestPlan) -> list[GeneratedTest]:
        """Generate unit tests for all components in a test plan.
        Args:
            test_plan: TestPlan with populated unit_scope.

        Returns:
            List of GeneratedTest objects, one per component (those
            that succeeded). Failed components are skipped.
        """
        state: dict = {
            "test_plan": test_plan,
            "messages": [],
        }
        result = unit_test_gen_node(state, config=self._config)
        return result.get("unit_tests", [])

    def generate_for_module(
        self,
        component: str,
        module: str,
        project_summary: str = "",
    ) -> GeneratedTest:
        """Generate tests for a single module.
        Args:
            component: Class or module name to test.
            module: Dotted import path (e.g. "auth.service").
            project_summary: Brief context for the LLM.

        Returns:
            A single GeneratedTest.

        Raises:
            RuntimeError: If generation fails or returns no results.
        """
        plan = TestPlan(
            project_summary=project_summary,
            unit_scope=[
                UnitScopeItem(component=component, module=module),
            ],
        )
        tests = self.generate(plan)
        if not tests:
            raise RuntimeError(
                f"Unit test generation produced no results for "
                f"{component} ({module}). Check logs for details."
            )
        return tests[0]

    def generate_batch(
        self,
        components: list[tuple[str, str]],
        project_summary: str = "",
    ) -> list[GeneratedTest]:
        """Generate tests for multiple modules at once.
        Args:
            components: List of (component_name, module_path) tuples.
            project_summary: Brief context for the LLM.

        Returns:
            List of GeneratedTest objects.
        """
        plan = TestPlan(
            project_summary=project_summary,
            unit_scope=[
                UnitScopeItem(component=name, module=mod)
                for name, mod in components
            ],
        )
        return self.generate(plan)

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════
def _extract_model_name(llm: BaseChatModel) -> str:
    """Best-effort extraction of the model identifier from a chat model.
    Different LangChain chat model classes store the model name in
    different attributes. This checks the common ones.
    """
    for attr in ("model", "model_name", "deployment_name", "model_id"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return type(llm).__name__