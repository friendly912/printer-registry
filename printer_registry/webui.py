"""Local web UI for the registration/verification terminal.

This is a presentation layer only: it calls the exact same crypto/db/judge
modules the CLI uses, so registering or verifying a printer here and via
`python -m printer_registry.cli` operate on the same local terminal state
(same DB, same keys, same mock NVRAM file).

Intended to run on the terminal itself (127.0.0.1) for the field operator
to use from a browser -- not to be exposed on a network.
"""
from __future__ import annotations

import hashlib

from flask import Flask, redirect, render_template, request, url_for

from . import crypto, db
from .config import DATA_DIR, ISSUER_ID, LOCAL_DB_PATH, MOCK_NVRAM_PATH, PRIVATE_KEY_PATH, PUBLIC_KEY_PATH
from .pjl_usb_backend import PJLUSBBackend
from .printer_iface import MockPrinterBackend, PrinterBackend
from .judge import verify_printer
from .token import issue_token

app = Flask(__name__)


def _hash_device_ref(device_ref: str) -> str:
    return hashlib.sha256(device_ref.encode("utf-8")).hexdigest()[:16]


def _make_backend(backend_name: str) -> PrinterBackend:
    if backend_name == "pjl-usb":
        return PJLUSBBackend()
    return MockPrinterBackend(MOCK_NVRAM_PATH)


@app.before_request
def _ensure_keys() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not PRIVATE_KEY_PATH.exists():
        crypto.generate_keypair(PRIVATE_KEY_PATH, PUBLIC_KEY_PATH)


@app.route("/")
def index():
    conn = db.connect(LOCAL_DB_PATH)
    with conn:
        printers = conn.execute(
            "SELECT printer_id, model, location, status, registered_at "
            "FROM printers ORDER BY registered_at DESC"
        ).fetchall()
        logs = conn.execute(
            "SELECT seq, event_type, printer_id, result, detail, timestamp "
            "FROM operation_log ORDER BY seq DESC LIMIT 20"
        ).fetchall()
    chain_ok = db.verify_log_chain(conn)
    return render_template("index.html", printers=printers, logs=logs, chain_ok=chain_ok)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        device_ref = request.form["device_ref"].strip()
        model = request.form.get("model", "").strip() or "unknown"
        location = request.form.get("location", "").strip() or "unknown"
        backend_name = request.form.get("backend", "mock")

        private_key = crypto.load_private_key(PRIVATE_KEY_PATH)
        conn = db.connect(LOCAL_DB_PATH)
        backend = _make_backend(backend_name)

        printer_id = _hash_device_ref(device_ref)
        tok = issue_token(printer_id=printer_id, issuer_id=ISSUER_ID, private_key=private_key)

        with backend:
            backend.connect(device_ref)
            backend.write_token(tok.to_wire_string())

        db.register_printer(conn, printer_id, model=model, location=location)
        db.store_token(conn, printer_id, tok.token_id, tok.issued_at, tok.issuer_id, tok.signature_hex)
        db.append_log(conn, "register", printer_id, "registered", f"device_ref={device_ref}")

        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    result = None
    detail = None
    device_ref = None

    if request.method == "POST":
        device_ref = request.form["device_ref"].strip()
        backend_name = request.form.get("backend", "mock")

        public_key = crypto.load_public_key(PUBLIC_KEY_PATH)
        conn = db.connect(LOCAL_DB_PATH)
        backend = _make_backend(backend_name)

        verdict, detail = verify_printer(backend, device_ref, public_key, conn)
        result = verdict.value

    return render_template("verify.html", result=result, detail=detail, device_ref=device_ref)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
