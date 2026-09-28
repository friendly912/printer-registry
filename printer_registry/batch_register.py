"""Batch registration: detect several connected printers and register each
in one pass, instead of running `register` once per device.

For the pjl-usb backend, "detection" means globbing for USB printer device
files (e.g. /dev/usb/lp*). There is no hardware here to test that glob
against, so discover_devices() is exercised in tests against a temp
directory standing in for /dev/usb. For the mock backend there is nothing
to scan on disk, so the caller supplies device refs explicitly.

A device path is just today's OS-assigned handle, not a stable printer
identity -- the same physical printer can show up as /dev/usb/lp0 on one
visit and /dev/usb/lp1 on the next. So "already registered?" is decided by
reading the token actually stored on the device (via judge.verify_printer),
not by looking up the device path in the local DB.
"""
from __future__ import annotations

import csv
import glob as glob_module
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey, EllipticCurvePublicKey

from . import db
from .judge import VerificationResult, verify_printer
from .printer_iface import PrinterBackend
from .token import issue_token


def discover_devices(pattern: str) -> list[str]:
    """Glob for candidate device paths (real hardware: /dev/usb/lp*)."""
    return sorted(glob_module.glob(pattern))


def load_metadata_csv(path: Path) -> dict[str, dict[str, str]]:
    """CSV columns: device_ref,model,location"""
    metadata: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            device_ref = row["device_ref"].strip()
            metadata[device_ref] = {
                "model": (row.get("model") or "").strip(),
                "location": (row.get("location") or "").strip(),
            }
    return metadata


def _hash_device_ref(device_ref: str) -> str:
    return hashlib.sha256(device_ref.encode("utf-8")).hexdigest()[:16]


class Outcome(Enum):
    REGISTERED = "registered"                   # newly registered this run
    ALREADY_REGISTERED = "already_registered"    # device already held a valid token
    NEEDS_REVIEW = "needs_review"                # tamper_suspected -- left untouched
    FAILED = "failed"                            # connection / write error


@dataclass
class DeviceResult:
    device_ref: str
    outcome: Outcome
    printer_id: Optional[str] = None
    detail: str = ""


BackendFactory = Callable[[], PrinterBackend]


def register_batch(
    device_refs: list[str],
    metadata: dict[str, dict[str, str]],
    default_model: str,
    default_location: str,
    private_key: EllipticCurvePrivateKey,
    public_key: EllipticCurvePublicKey,
    conn,
    backend_factory: BackendFactory,
    issuer_id: str,
) -> list[DeviceResult]:
    results: list[DeviceResult] = []

    for device_ref in device_refs:
        try:
            precheck, precheck_detail = verify_printer(backend_factory(), device_ref, public_key, conn)
        except Exception as exc:
            results.append(DeviceResult(device_ref, Outcome.FAILED, detail=str(exc)))
            continue

        if precheck == VerificationResult.REGISTERED:
            printer_id = precheck_detail.split("printer_id=")[-1]
            results.append(DeviceResult(device_ref, Outcome.ALREADY_REGISTERED, printer_id, precheck_detail))
            continue

        if precheck == VerificationResult.TAMPER_SUSPECTED:
            results.append(DeviceResult(device_ref, Outcome.NEEDS_REVIEW, detail=precheck_detail))
            continue

        meta = metadata.get(device_ref, {})
        model = meta.get("model") or default_model
        location = meta.get("location") or default_location
        printer_id = _hash_device_ref(device_ref)

        try:
            tok = issue_token(printer_id=printer_id, issuer_id=issuer_id, private_key=private_key)
            backend = backend_factory()
            with backend:
                backend.connect(device_ref)
                backend.write_token(tok.to_wire_string())

            db.register_printer(conn, printer_id, model=model, location=location)
            db.store_token(conn, printer_id, tok.token_id, tok.issued_at, tok.issuer_id, tok.signature_hex)
            db.append_log(conn, "register", printer_id, "registered", f"device_ref={device_ref} (batch)")

            results.append(DeviceResult(device_ref, Outcome.REGISTERED, printer_id))
        except Exception as exc:
            results.append(DeviceResult(device_ref, Outcome.FAILED, detail=str(exc)))

    return results
