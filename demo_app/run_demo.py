"""Run QAura against the demo application.

This script demonstrates how to configure and invoke the QAura pipeline
against the demo e-commerce app. It prepares the initial state and
shows the expected workflow.

IMPORTANT: Requires API keys in the .env file at the project root.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.graph import build_qaura_graph
from core.state import QAuraState


DEMO_REQUIREMENTS = """
# QAura Demo Store — Requirements for Testing

## Application Overview
A simple e-commerce web application (FastAPI + SQLite) with:
- User registration and login (email/password)
- Product catalog browsing
- Order placement (authenticated users)
- User dashboard showing order history

## Source Files Under Test
- demo_app/server.py      — FastAPI routes and middleware
- demo_app/auth.py         — Authentication: register, login, session management
- demo_app/orders.py       — Product listing, order calculation, order placement
- demo_app/models.py       — SQLite database schema and seed data
- demo_app/templates/      — HTML frontend (login, dashboard, product listing)

## Functional Requirements
1. Users can register with email, password, and name
2. Users can log in and receive a session token
3. Authenticated users can browse products
4. Authenticated users can place orders
5. Users can view their own order history on the dashboard
6. Users can log out, invalidating their session

## Known Risk Areas (for QAura to discover)
- Authentication module may have SQL injection vectors
- Password storage practices
- Session expiry validation
- Order calculation logic (discounts)
- Stock management during ordering
- Authorization on user-specific endpoints
- Input validation on all forms (XSS, injection)

## API Endpoints
- POST /api/auth/register  — Register new user
- POST /api/auth/login     — Login, receive token
- DELETE /api/auth/logout   — Logout, invalidate session
- GET  /api/products        — List all products
- GET  /api/products/{id}   — Get single product
- POST /api/orders          — Place an order (auth required)
- GET  /api/orders           — Get current user's orders (auth required)
- GET  /api/users/{id}/orders — Get orders by user ID (NO AUTH — vulnerability)

## Frontend Pages
- / (Home)              — Product listing with order buttons
- /login                — Login and registration forms
- /dashboard            — User dashboard with order history
"""


def run_demo():
    """Configure and run QAura against the demo app."""
    print("=" * 60)
    print("  QAura Demo — Testing the Demo Store App")
    print("=" * 60)
    print()

    app = build_qaura_graph()
    print("[OK] QAura graph compiled.")

    initial_state: QAuraState = {
        "input_type": "requirements",
        "input_source": DEMO_REQUIREMENTS,
        "test_plan": None,
        "plan_approved": False,
        "unit_tests": [],
        "integration_tests": [],
        "e2e_tests": [],
        "environment_ready": False,
        "environment_details": "",
        "execution_results": [],
        "all_passed": False,
        "root_cause_analyses": [],
        "healing_actions": [],
        "retry_count": 0,
        "max_retries": 3,
        "final_report": "",
        "current_phase": "initialized",
        "messages": ["[QAura] Demo pipeline initialized."],
    }

    print("[OK] Initial state configured with demo app requirements.")
    print()
    print("To execute (requires API keys in .env):")
    print()
    print("  from langgraph.checkpoint.memory import MemorySaver")
    print("  checkpointer = MemorySaver()")
    print("  config = {'configurable': {'thread_id': 'demo-run-1'}}")
    print()
    print("  # Step 1: Run until HITL interrupt (test plan approval)")
    print("  result = app.invoke(initial_state, config=config)")
    print()
    print("  # Step 2: Review the test plan")
    print("  state = app.get_state(config)")
    print("  print(state.values['test_plan'])")
    print()
    print("  # Step 3: Approve and continue")
    print("  app.invoke({'approved': True}, config=config)")
    print()


if __name__ == "__main__":
    run_demo()
