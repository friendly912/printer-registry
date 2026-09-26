"""Local terminal database: registered-printer snapshot + a hash-chained
operation log.

Phase 0 uses plain SQLite. In Phase 1 this becomes an encrypted store
(e.g. SQLCipher) unlocked by the terminal's biometric/PIN -- the schema and
queries below don't need to change, only the connection setup.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS printers (
    printer_id   TEXT PRIMARY KEY,
    model        TEXT,
    location     TEXT,
    status       TEXT NOT NULL DEFAULT 'registered',
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    token_id     TEXT PRIMARY KEY,
    printer_id   TEXT NOT NULL,
    issued_at    TEXT NOT NULL,
    issuer_id    TEXT NOT NULL,
    signature_hex TEXT NOT NULL,
    revoked      INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (printer_id) REFERENCES printers (printer_id)
);

CREATE TABLE IF NOT EXISTS operation_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,   -- 'register' | 'verify'
    printer_id   TEXT,
    result       TEXT NOT NULL,   -- 'registered' | 'not_registered' | 'tamper_suspected'
    detail       TEXT,
    timestamp    TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
"""

GENESIS_HASH = "0" * 64


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def register_printer(conn: sqlite3.Connection, printer_id: str, model: str, location: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO printers (printer_id, model, location, status, registered_at) "
        "VALUES (?, ?, ?, 'registered', ?)",
        (printer_id, model, location, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def store_token(conn: sqlite3.Connection, printer_id: str, token_id: str, issued_at: str,
                 issuer_id: str, signature_hex: str) -> None:
    conn.execute(
        "INSERT INTO tokens (token_id, printer_id, issued_at, issuer_id, signature_hex) "
        "VALUES (?, ?, ?, ?, ?)",
        (token_id, printer_id, issued_at, issuer_id, signature_hex),
    )
    conn.commit()


def is_printer_registered(conn: sqlite3.Connection, printer_id: str) -> bool:
    with closing(conn.execute(
        "SELECT status FROM printers WHERE printer_id = ?", (printer_id,)
    )) as cur:
        row = cur.fetchone()
    return row is not None and row[0] == "registered"


def _last_entry_hash(conn: sqlite3.Connection) -> str:
    with closing(conn.execute(
        "SELECT entry_hash FROM operation_log ORDER BY seq DESC LIMIT 1"
    )) as cur:
        row = cur.fetchone()
    return row[0] if row else GENESIS_HASH


def append_log(conn: sqlite3.Connection, event_type: str, printer_id: Optional[str],
               result: str, detail: str = "") -> None:
    prev_hash = _last_entry_hash(conn)
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(
        {
            "event_type": event_type,
            "printer_id": printer_id,
            "result": result,
            "detail": detail,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
    )
    entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO operation_log (event_type, printer_id, result, detail, timestamp, prev_hash, entry_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_type, printer_id, result, detail, timestamp, prev_hash, entry_hash),
    )
    conn.commit()


def verify_log_chain(conn: sqlite3.Connection) -> bool:
    """Recompute the hash chain to detect any tampering with the local log."""
    prev_hash = GENESIS_HASH
    with closing(conn.execute(
        "SELECT event_type, printer_id, result, detail, timestamp, prev_hash, entry_hash "
        "FROM operation_log ORDER BY seq ASC"
    )) as cur:
        rows = cur.fetchall()

    for event_type, printer_id, result, detail, timestamp, stored_prev_hash, stored_entry_hash in rows:
        if stored_prev_hash != prev_hash:
            return False
        payload = json.dumps(
            {
                "event_type": event_type,
                "printer_id": printer_id,
                "result": result,
                "detail": detail,
                "timestamp": timestamp,
                "prev_hash": stored_prev_hash,
            },
            sort_keys=True,
        )
        recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if recomputed != stored_entry_hash:
            return False
        prev_hash = stored_entry_hash

    return True
