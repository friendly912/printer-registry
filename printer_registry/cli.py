"""Command-line entry points standing in for the registration terminal app
and the verification terminal app (Phase 0: same process, mock backend).

Usage:
    python -m printer_registry.cli init-keys
    python -m printer_registry.cli register --device-ref usb:0001 --model "Canon X1" --location "本社3F"
    python -m printer_registry.cli verify --device-ref usb:0001
    python -m printer_registry.cli tamper --device-ref usb:0001     # demo: corrupt a stored token
    python -m printer_registry.cli show-log
"""
from __future__ import annotations

import argparse
import hashlib
import sys

from . import crypto, db
from .config import DATA_DIR, ISSUER_ID, LOCAL_DB_PATH, MOCK_NVRAM_PATH, PRIVATE_KEY_PATH, PUBLIC_KEY_PATH
from .judge import verify_printer
from .pjl_usb_backend import PJLUSBBackend
from .printer_iface import MockPrinterBackend, PrinterBackend
from .token import issue_token


def _hash_device_ref(device_ref: str) -> str:
    """Stand-in for hashing a printer's real serial number into printer_id."""
    return hashlib.sha256(device_ref.encode("utf-8")).hexdigest()[:16]


def _make_backend(args: argparse.Namespace) -> PrinterBackend:
    if args.backend == "pjl-usb":
        # --device-ref is then a real path, e.g. /dev/usb/lp0
        return PJLUSBBackend()
    return MockPrinterBackend(MOCK_NVRAM_PATH)


def _add_backend_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=["mock", "pjl-usb"],
        default="mock",
        help="mock: simulated NVRAM (default). pjl-usb: real device over "
             "--device-ref as a USB printer device path (untested against actual hardware).",
    )


def cmd_init_keys(_args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if PRIVATE_KEY_PATH.exists():
        print(f"keys already exist at {DATA_DIR}")
        return
    crypto.generate_keypair(PRIVATE_KEY_PATH, PUBLIC_KEY_PATH)
    print(f"generated keypair:\n  private: {PRIVATE_KEY_PATH}\n  public:  {PUBLIC_KEY_PATH}")


def cmd_register(args: argparse.Namespace) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    private_key = crypto.load_private_key(PRIVATE_KEY_PATH)
    conn = db.connect(LOCAL_DB_PATH)
    backend = _make_backend(args)

    printer_id = _hash_device_ref(args.device_ref)
    tok = issue_token(printer_id=printer_id, issuer_id=ISSUER_ID, private_key=private_key)

    with backend:
        backend.connect(args.device_ref)
        backend.write_token(tok.to_wire_string())

    db.register_printer(conn, printer_id, model=args.model, location=args.location)
    db.store_token(conn, printer_id, tok.token_id, tok.issued_at, tok.issuer_id, tok.signature_hex)
    db.append_log(conn, "register", printer_id, "registered", f"device_ref={args.device_ref}")

    print(f"registered device_ref={args.device_ref} -> printer_id={printer_id}")
    print(f"token_id={tok.token_id}")


def cmd_verify(args: argparse.Namespace) -> None:
    public_key = crypto.load_public_key(PUBLIC_KEY_PATH)
    conn = db.connect(LOCAL_DB_PATH)
    backend = _make_backend(args)

    result, detail = verify_printer(backend, args.device_ref, public_key, conn)
    print(f"device_ref={args.device_ref} -> {result.value}")
    print(f"  detail: {detail}")


def cmd_tamper(args: argparse.Namespace) -> None:
    """Demo helper: simulate someone corrupting the stored token, to exercise
    the tamper_suspected branch of the judgment logic."""
    backend = MockPrinterBackend(MOCK_NVRAM_PATH)
    with backend:
        backend.connect(args.device_ref)
        raw = backend.read_token()
        if raw is None:
            print("no token to tamper with; register first")
            return
        tampered = raw.replace('"issuer_id"', '"issuer_id_x"', 1)
        backend.write_token(tampered)
    print(f"tampered token for device_ref={args.device_ref}")


def cmd_show_log(_args: argparse.Namespace) -> None:
    conn = db.connect(LOCAL_DB_PATH)
    chain_ok = db.verify_log_chain(conn)
    print(f"log chain intact: {chain_ok}")
    with conn:
        for row in conn.execute(
            "SELECT seq, event_type, printer_id, result, detail, timestamp FROM operation_log ORDER BY seq"
        ):
            print(f"  #{row[0]:03d} {row[5]}  {row[1]:8s} printer_id={row[2]!s:18s} "
                  f"result={row[3]:16s} {row[4]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="printer_registry")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-keys").set_defaults(func=cmd_init_keys)

    p_register = sub.add_parser("register")
    p_register.add_argument("--device-ref", required=True, help="stand-in for USB device path / serial")
    p_register.add_argument("--model", default="unknown")
    p_register.add_argument("--location", default="unknown")
    _add_backend_flag(p_register)
    p_register.set_defaults(func=cmd_register)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--device-ref", required=True)
    _add_backend_flag(p_verify)
    p_verify.set_defaults(func=cmd_verify)

    p_tamper = sub.add_parser("tamper")
    p_tamper.add_argument("--device-ref", required=True)
    p_tamper.set_defaults(func=cmd_tamper)

    sub.add_parser("show-log").set_defaults(func=cmd_show_log)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
