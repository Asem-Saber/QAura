# core/state.py
"""QAura shared state and Pydantic schemas.

This file grows as more agents are implemented. Only unit-test-relevant
types are defined here for now.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────

class Phase(str, Enum):
    INITIALIZED = "initialized"
    PLANNING = "planning"
    GENERATION = "generation"
    ENVIRONMENT = "environment"
    EXECUTION = "execution"
    HEALING = "healing"
    REPORTING = "reporting"
    DONE = "done"

class InputType(str, Enum):
    GIT_PR = "git_pr"
    REQUIREMENTS = "requirements"

class TestCategory(str, Enum):
    HAPPY = "happy"
    EDGE = "edge"
    ERROR = "error"
    BOUNDARY = "boundary"

# ── Planning Models (consumed by Unit Gen) ─────────────────────────────

class UnitScopeItem(BaseModel):
    component: str = Field(..., description="Class or module name to test")
    module: str = Field(..., description="Dotted import path, e.g. 'auth.service'")

class TestPlan(BaseModel):
    project_summary: str = ""
    unit_scope: list[UnitScopeItem] = Field(default_factory=list)
    integration_scope: list[str] = Field(default_factory=list)
    e2e_scope: list[str] = Field(default_factory=list)
    security_scope: list[str] = Field(default_factory=list)

# ── Generation Output Models ───────────────────────────────────────────

class TestCaseMeta(BaseModel):
    """Metadata for a single test function within a generated file."""

    name: str = Field(..., description="e.g. test_create_user_valid_email_returns_user")
    category: TestCategory
    target_symbol: str = Field(..., description="Exact function/method being exercised")
    assertion_count: int = Field(ge=1, description="Number of assert statements")

class GeneratedTest(BaseModel):
    """A single generated test file and its metadata."""

    file_name: str = Field(..., description="e.g. test_user_service.py")
    test_code: str
    framework: str = "pytest"
    target_component: str = ""
    target_module: str = ""
    covered_symbols: list[str] = Field(default_factory=list)
    test_cases: list[TestCaseMeta] = Field(default_factory=list)
    conftest_contribution: str | None = None
    syntax_validated: bool = False
    generator_model: str = ""
    coverage_notes: str = ""

# ── LangGraph State ────────────────────────────────────────────────────

class QAuraState(TypedDict, total=False):
    # Phase 1 — Input & Planning
    input_type: InputType
    input_source: str
    test_plan: TestPlan | None
    plan_approved: bool

    # Phase 2 — Generation (parallel branches write distinct keys)
    unit_tests: list[GeneratedTest]
    integration_tests: list[GeneratedTest]
    e2e_tests: list[GeneratedTest]

    # Phase 3-5 placeholders (other agents fill these in)
    environment_ready: bool
    environment_details: str
    execution_results: list[Any]
    all_passed: bool
    root_cause_analyses: list[Any]
    healing_actions: list[Any]
    retry_count: int
    max_retries: int

    # Cross-phase
    final_report: str
    current_phase: Phase
    # messages uses add reducer so parallel agents don't overwrite each other
    messages: Annotated[list[str], operator.add]