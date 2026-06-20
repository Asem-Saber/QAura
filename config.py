# config.py
"""Centralized configuration: logging, LLM selection, project paths."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from langchain_core.language_models import BaseChatModel

# ── Paths ──────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(os.getenv("QAURA_PROJECT_ROOT", ".")).resolve()
TESTS_DIR = PROJECT_ROOT / "tests"
CONFTEST_PATH = TESTS_DIR / "conftest.py"

# ── Logging ────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with a consistent format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

# ── LLM Factory ────────────────────────────────────────────────────────

def get_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
) -> BaseChatModel:
    """Return a chat model based on environment or explicit override.

    Priority:
        1. Explicit provider argument
        2. QAURA_DEFAULT_LLM env var
        3. First available API key found
    """
    provider = provider or os.getenv("QAURA_DEFAULT_LLM", "")
    provider = provider.lower().strip()

    if not provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        elif os.getenv("GROQ_API_KEY"):
            provider = "groq"
        elif os.getenv("TOGETHER_API_KEY"):
            provider = "together"
        else:
            raise RuntimeError(
                "No LLM provider configured. Set one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, "
                "TOGETHER_API_KEY, or QAURA_DEFAULT_LLM."
            )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model or "claude-3-5-sonnet-20241022",
            temperature=temperature,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "gpt-4o",
            temperature=temperature,
        )

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model or "llama-3.3-70b-versatile",
            temperature=temperature,
        )

    if provider == "together":
        from langchain_together import ChatTogether
        return ChatTogether(
            model=model or "deepseek-ai/DeepSeek-Coder-V2-Instruct",
            temperature=temperature,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")