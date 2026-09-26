"""Shared paths/constants for the local terminal (registration key, local
DB, mock NVRAM file). Used by both the CLI and the web UI so they operate
on the same terminal state.
"""
from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRIVATE_KEY_PATH = DATA_DIR / "registration_private.pem"
PUBLIC_KEY_PATH = DATA_DIR / "registration_public.pem"
LOCAL_DB_PATH = DATA_DIR / "terminal.sqlite3"
MOCK_NVRAM_PATH = DATA_DIR / "mock_printer_nvram.json"
ISSUER_ID = "poc-registration-terminal-01"
