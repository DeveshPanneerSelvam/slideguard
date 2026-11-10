"""SQLite storage for QC results, rescan requests, and the audit trail.

Rescan requests move pending_approval -> approved | rejected. Only a named
person can approve (slideguard/cli.py); the MCP server can draft but not approve.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS slides (
    slide_id TEXT PRIMARY KEY, path TEXT, checked_at TEXT,
    passed INTEGER, failures TEXT, metrics TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slide_id TEXT, body TEXT, status TEXT,
    created_at TEXT, reviewed_by TEXT, reviewed_at TEXT, edited INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, actor TEXT, action TEXT,
    slide_id TEXT, request_id INTEGER, detail TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def log_event(conn, actor, action, slide_id, request_id=None, detail="") -> None:
    conn.execute(
        "INSERT INTO events (at, actor, action, slide_id, request_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (_now(), actor, action, slide_id, request_id, detail),
    )


def save_result(conn, slide_id: str, path: str, result, actor: str = "qc") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO slides VALUES (?, ?, ?, ?, ?, ?)",
        (slide_id, path, _now(), int(result.passed),
         json.dumps(result.failures), json.dumps(result.metrics)),
    )
    log_event(conn, actor, "qc_passed" if result.passed else "qc_failed", slide_id)
    conn.commit()


def slide(conn, slide_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM slides WHERE slide_id = ?", (slide_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["passed"] = bool(data["passed"])
    data["failures"] = json.loads(data["failures"])
    data["metrics"] = json.loads(data["metrics"])
    return data


def slides(conn, passed: bool | None = None) -> list[dict]:
    query, args = "SELECT slide_id FROM slides", ()
    if passed is not None:
        query, args = query + " WHERE passed = ?", (int(passed),)
    return [slide(conn, r["slide_id"]) for r in conn.execute(query + " ORDER BY slide_id", args)]


def save_request(conn, slide_id: str, body: str, actor: str) -> int:
    cur = conn.execute(
        "INSERT INTO requests (slide_id, body, status, created_at) VALUES (?, ?, 'pending_approval', ?)",
        (slide_id, body, _now()),
    )
    log_event(conn, actor, "rescan_drafted", slide_id, cur.lastrowid)
    conn.commit()
    return cur.lastrowid


def requests(conn, status: str | None = None) -> list[dict]:
    query, args = "SELECT * FROM requests", ()
    if status:
        query, args = query + " WHERE status = ?", (status,)
    return [dict(r) for r in conn.execute(query + " ORDER BY id", args)]


def review_request(conn, request_id: int, reviewer: str, approve: bool, new_body: str | None = None) -> dict:
    if not reviewer.strip():
        raise ValueError("A named reviewer is required")
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not row:
        raise ValueError(f"Request {request_id} not found")
    if row["status"] != "pending_approval":
        raise ValueError(f"Request {request_id} is already {row['status']}")
    status = "approved" if approve else "rejected"
    edited = int(bool(new_body) and new_body != row["body"])
    conn.execute(
        "UPDATE requests SET status = ?, reviewed_by = ?, reviewed_at = ?, edited = ?, body = ? WHERE id = ?",
        (status, reviewer, _now(), edited, new_body or row["body"], request_id),
    )
    log_event(conn, reviewer, status, row["slide_id"], request_id, "edited" if edited else "")
    conn.commit()
    return {"request_id": request_id, "status": status, "edited": bool(edited)}
