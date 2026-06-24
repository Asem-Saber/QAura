"""QAura Demo App — Authentication Module.

Handles user login, registration, session management.
Contains intentional security vulnerabilities for QAura to detect.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from models import get_db


def register_user(email: str, password: str, name: str) -> dict:
    """Register a new user.

    BUG: No password strength validation.
    BUG: No email format validation.
    """
    conn = get_db()
    cursor = conn.cursor()

    try:
        # VULNERABILITY: Password stored as plain text
        cursor.execute(
            "INSERT INTO users (email, password, name) VALUES (?, ?, ?)",
            (email, password, name),
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {"id": user_id, "email": email, "name": name, "role": "user"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def login_user(email: str, password: str) -> dict:
    """Authenticate a user and create a session.

    VULNERABILITY: SQL injection in email parameter.
    BUG: No rate limiting on login attempts.
    """
    conn = get_db()
    cursor = conn.cursor()

    # VULNERABILITY: SQL injection — string concatenation instead of parameterized query
    query = f"SELECT * FROM users WHERE email = '{email}' AND password = '{password}'"
    cursor.execute(query)
    user = cursor.fetchone()

    if user is None:
        conn.close()
        return {"error": "Invalid email or password"}

    token = secrets.token_hex(32)
    # BUG: Session expiry set to 30 days (too long)
    expires = datetime.now() + timedelta(days=30)
    cursor.execute(
        "INSERT INTO sessions (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires.isoformat()),
    )
    conn.commit()
    conn.close()

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
        },
    }


def validate_session(token: str) -> dict | None:
    """Validate a session token and return the user.

    BUG: Does not check if the session has expired.
    """
    conn = get_db()
    cursor = conn.cursor()

    # BUG: Missing expiry check — expired sessions are still valid
    cursor.execute(
        "SELECT s.*, u.email, u.name, u.role FROM sessions s "
        "JOIN users u ON s.user_id = u.id WHERE s.token = ?",
        (token,),
    )
    session = cursor.fetchone()
    conn.close()

    if session is None:
        return None

    return {
        "id": session["user_id"],
        "email": session["email"],
        "name": session["name"],
        "role": session["role"],
    }


def logout_user(token: str) -> bool:
    """Invalidate a session."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0
