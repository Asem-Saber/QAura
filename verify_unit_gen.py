# verify_unit_gen.py
"""Verification script for the Unit Test Generator.

Tests internal logic (coverage, validation, formatting) without
requiring an LLM API key. Run with: python verify_unit_gen.py
"""

from __future__ import annotations

import ast
import sys
from unittest.mock import MagicMock

# ── Test fixtures ──────────────────────────────────────────────────────

SAMPLE_SOURCE = '''\
"""Sample service for verification."""

from typing import Optional

class ConflictError(Exception):
    pass

class UserService:
    def __init__(self, db_session, clock=None):
        self.db = db_session
        self.clock = clock

    def create_user(self, email: str, password: str) -> dict:
        if not email or "@" not in email:
            raise ValueError("Invalid email")
        if len(password) < 8:
            raise ValueError("Password too short")
        existing = self.db.query().filter(email=email).first()
        if existing:
            raise ConflictError("Email already registered")
        user = {"email": email, "password": password}
        self.db.add(user)
        return user

    def get_user(self, email: str) -> Optional[dict]:
        if not email:
            raise ValueError("Email required")
        return self.db.query().filter(email=email).first()

    def _private_helper(self):
        pass

def validate_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[1]
'''

VALID_TEST_CODE = '''\
import pytest
from unittest.mock import Mock
from auth.service import UserService, ConflictError

@pytest.fixture
def mock_db():
    return Mock()

@pytest.fixture
def service(mock_db):
    return UserService(db_session=mock_db)

def test_create_user_valid_email_returns_user(service, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    result = service.create_user("test@example.com", "SecurePass1")
    assert result["email"] == "test@example.com"
    mock_db.add.assert_called_once()

def test_create_user_duplicate_email_raises_conflict(service, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = Mock()
    with pytest.raises(ConflictError):
        service.create_user("existing@example.com", "password123")

def test_get_user_existing_returns_user(service, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = {"email": "x"}
    assert service.get_user("x@example.com") is not None
'''

INVALID_TEST_CODE = '''\
def test_broken(
    assert True
'''

# ── Import the agent module ────────────────────────────────────────────

sys.path.insert(0, ".")
from agents.unit_test_gen import (
    _extract_public_symbols,
    _is_public,
    _verify_coverage,
    _verify_test_cases,
    _validate_and_retry,
    _format_success_message,
    _extract_model_name,
    GenerationConfig,
)
from core.state import GeneratedTest, TestCaseMeta, TestCategory

# ── Test runner ────────────────────────────────────────────────────────

passed = 0
failed = 0

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} — {detail}")
        failed += 1

# ── Tests ──────────────────────────────────────────────────────────────

def test_is_public():
    print("\n=== _is_public ===")
    check("public name", _is_public("create_user"))
    check("init is public", _is_public("__init__"))
    check("private not public", not _is_public("_private_helper"))
    check("dunder not public", not _is_public("__str__"))

def test_extract_public_symbols():
    print("\n=== _extract_public_symbols ===")
    symbols = _extract_public_symbols(SAMPLE_SOURCE)
    check("UserService found", "UserService" in symbols)
    check("create_user found", "create_user" in symbols)
    check("get_user found", "get_user" in symbols)
    check("validate_email found", "validate_email" in symbols)
    check("_private_helper excluded", "_private_helper" not in symbols)
    check("ConflictError found", "ConflictError" in symbols)

def test_verify_coverage_complete():
    print("\n=== _verify_coverage (complete) ===")
    test = GeneratedTest(
        file_name="test_user_service.py",
        test_code=VALID_TEST_CODE,
        covered_symbols=[
            "UserService", "create_user", "get_user",
            "ConflictError", "validate_email",
        ],
        test_cases=[
            TestCaseMeta(
                name="test_create_user_valid_email_returns_user",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=2,
            ),
            TestCaseMeta(
                name="test_create_user_duplicate_email_raises_conflict",
                category=TestCategory.ERROR,
                target_symbol="create_user",
                assertion_count=1,
            ),
            TestCaseMeta(
                name="test_get_user_existing_returns_user",
                category=TestCategory.HAPPY,
                target_symbol="get_user",
                assertion_count=1,
            ),
        ],
    )
    gaps = _verify_coverage(test, SAMPLE_SOURCE)
    check(
        "no uncovered symbols",
        not any("Uncovered" in g for g in gaps),
        str(gaps),
    )

def test_verify_coverage_with_gaps():
    print("\n=== _verify_coverage (with gaps) ===")
    test = GeneratedTest(
        file_name="test_x.py",
        test_code="pass",
        covered_symbols=["create_user"],
        test_cases=[
            TestCaseMeta(
                name="test_create",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=1,
            ),
        ],
    )
    gaps = _verify_coverage(test, SAMPLE_SOURCE)
    gap_text = "\n".join(gaps)
    check("get_user flagged as uncovered", "get_user" in gap_text)
    check("validate_email flagged", "validate_email" in gap_text)

def test_verify_test_cases_matching():
    print("\n=== _verify_test_cases (matching) ===")
    test = GeneratedTest(
        file_name="test_user_service.py",
        test_code=VALID_TEST_CODE,
        test_cases=[
            TestCaseMeta(
                name="test_create_user_valid_email_returns_user",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=2,
            ),
            TestCaseMeta(
                name="test_create_user_duplicate_email_raises_conflict",
                category=TestCategory.ERROR,
                target_symbol="create_user",
                assertion_count=1,
            ),
            TestCaseMeta(
                name="test_get_user_existing_returns_user",
                category=TestCategory.HAPPY,
                target_symbol="get_user",
                assertion_count=1,
            ),
        ],
    )
    warnings = _verify_test_cases(test)
    check("no warnings", len(warnings) == 0, str(warnings))

def test_verify_test_cases_hallucinated():
    print("\n=== _verify_test_cases (hallucinated) ===")
    test = GeneratedTest(
        file_name="test_x.py",
        test_code=VALID_TEST_CODE,
        test_cases=[
            TestCaseMeta(
                name="test_create_user_valid_email_returns_user",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=2,
            ),
            TestCaseMeta(
                name="test_fake_function_that_doesnt_exist",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=1,
            ),
        ],
    )
    warnings = _verify_test_cases(test)
    check(
        "hallucinated test detected",
        any("not in code" in w for w in warnings),
        str(warnings),
    )
    check(
        "undocumented test detected",
        any("not in test_cases" in w for w in warnings),
        str(warnings),
    )

def test_validate_and_retry_valid():
    print("\n=== _validate_and_retry (valid code) ===")
    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    test = GeneratedTest(
        file_name="test_x.py",
        test_code=VALID_TEST_CODE,
        target_component="UserService",
        target_module="auth.service",
    )
    result = _validate_and_retry(
        test=test,
        llm=mock_llm,
        component="UserService",
        module="auth.service",
        ast_inventory="- method: create_user",
        source_code="pass",
        max_retries=2,
    )
    check("syntax_validated is True", result.syntax_validated)

def test_validate_and_retry_invalid_no_retries():
    print("\n=== _validate_and_retry (invalid, 0 retries) ===")
    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    test = GeneratedTest(
        file_name="test_x.py",
        test_code=INVALID_TEST_CODE,
        target_component="UserService",
        target_module="auth.service",
    )
    result = _validate_and_retry(
        test=test,
        llm=mock_llm,
        component="UserService",
        module="auth.service",
        ast_inventory="n/a",
        source_code="pass",
        max_retries=0,
    )
    check("syntax_validated is False", not result.syntax_validated)

def test_format_success_message():
    print("\n=== _format_success_message ===")
    test = GeneratedTest(
        file_name="test_user_service.py",
        test_code=VALID_TEST_CODE,
        target_component="UserService",
        target_module="auth.service",
        syntax_validated=True,
        covered_symbols=["create_user", "get_user"],
        test_cases=[
            TestCaseMeta(
                name="t1",
                category=TestCategory.HAPPY,
                target_symbol="create_user",
                assertion_count=1,
            ),
        ],
        coverage_notes="All public symbols have associated test cases.",
    )
    msg = _format_success_message(test, "UserService")
    check("contains file name", "test_user_service.py" in msg)
    check("contains test count", "1 tests" in msg)
    check("contains validated", "validated" in msg)
    check("contains symbol count", "2 symbols" in msg)

def test_format_success_message_with_gaps():
    print("\n=== _format_success_message (with gaps) ===")
    test = GeneratedTest(
        file_name="test_x.py",
        test_code="pass",
        syntax_validated=False,
        covered_symbols=[],
        test_cases=[],
        coverage_notes="Uncovered symbols: get_user, delete_user",
    )
    msg = _format_success_message(test, "MyComponent")
    check("contains UNVALIDATED", "UNVALIDATED" in msg)
    check("contains gap info", "Uncovered symbols" in msg)

def test_extract_model_name():
    print("\n=== _extract_model_name ===")
    llm = MagicMock()
    llm.model = "claude-3-5-sonnet"
    check("extracts model attr", _extract_model_name(llm) == "claude-3-5-sonnet")

    llm2 = MagicMock()
    del llm2.model
    llm2.model_name = "gpt-4o"
    check("extracts model_name attr", _extract_model_name(llm2) == "gpt-4o")

    llm3 = MagicMock()
    check("falls back to class name", _extract_model_name(llm3) == "MagicMock")

def test_generation_config_defaults():
    print("\n=== GenerationConfig defaults ===")
    cfg = GenerationConfig()
    check("llm is None", cfg.llm is None)
    check("max_retries is 2", cfg.max_retries == 2)
    check("skip_unvalidated is False", cfg.skip_unvalidated is False)

# ── Run all tests ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Unit Test Generator — Verification")
    print("=" * 60)

    test_is_public()
    test_extract_public_symbols()
    test_verify_coverage_complete()
    test_verify_coverage_with_gaps()
    test_verify_test_cases_matching()
    test_verify_test_cases_hallucinated()
    test_validate_and_retry_valid()
    test_validate_and_retry_invalid_no_retries()
    test_format_success_message()
    test_format_success_message_with_gaps()
    test_extract_model_name()
    test_generation_config_defaults()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)