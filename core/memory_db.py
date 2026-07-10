import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "memory_db"
DB_PATH = DB_DIR / "history.sqlite3"


def _get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS test_executions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id     TEXT    NOT NULL,
            run_id      TEXT    NOT NULL,
            status      TEXT    NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            stack_trace TEXT    DEFAULT '',
            classification TEXT DEFAULT '',
            timestamp   TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_test_executions_test_id
            ON test_executions(test_id);

        CREATE TABLE IF NOT EXISTS healing_actions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            anomaly_id   TEXT NOT NULL,
            action_type  TEXT NOT NULL,
            target_file  TEXT DEFAULT '',
            original_code TEXT DEFAULT '',
            patched_code  TEXT DEFAULT '',
            explanation  TEXT DEFAULT '',
            success      INTEGER NOT NULL DEFAULT 1,
            timestamp    TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def log_execution(
    test_id: str,
    run_id: str,
    status: str,
    duration_ms: int = 0,
    stack_trace: str = "",
    classification: str = "",
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO test_executions
               (test_id, run_id, status, duration_ms, stack_trace, classification, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                test_id,
                run_id,
                status,
                duration_ms,
                stack_trace,
                classification,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_test_history(test_id: str) -> dict:
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT status, duration_ms, timestamp FROM test_executions WHERE test_id = ? ORDER BY timestamp DESC",
            (test_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"test_id": test_id, "total_runs": 0, "flakiness_rate": 0.0, "history": []}

    total = len(rows)
    failures = sum(1 for r in rows if r["status"] == "failed")
    passes = sum(1 for r in rows if r["status"] == "passed")

    flakiness_rate = 0.0
    if total >= 2 and passes > 0 and failures > 0:
        flakiness_rate = round(min(passes, failures) / total, 4)

    avg_duration = round(sum(r["duration_ms"] for r in rows) / total)

    return {
        "test_id": test_id,
        "total_runs": total,
        "passed": passes,
        "failed": failures,
        "flakiness_rate": flakiness_rate,
        "avg_duration_ms": avg_duration,
        "last_status": rows[0]["status"],
        "last_run": rows[0]["timestamp"],
    }


def log_healing_action(
    anomaly_id: str,
    action_type: str,
    target_file: str = "",
    original_code: str = "",
    patched_code: str = "",
    explanation: str = "",
    success: bool = True,
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO healing_actions
               (anomaly_id, action_type, target_file, original_code, patched_code, explanation, success, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                anomaly_id,
                action_type,
                target_file,
                original_code,
                patched_code,
                explanation,
                1 if success else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


# Auto-initialize tables on import
init_db()
