"""The three-way judgment logic used by the verification terminal:
registered / not_registered / tamper_suspected.
"""
from __future__ import annotations

from enum import Enum

from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey

from . import db, token as token_mod
from .printer_iface import PrinterBackend


class VerificationResult(Enum):
    REGISTERED = "registered"
    NOT_REGISTERED = "not_registered"
    TAMPER_SUSPECTED = "tamper_suspected"


def verify_printer(backend: PrinterBackend, device_ref: str, public_key: EllipticCurvePublicKey,
                    conn) -> tuple[VerificationResult, str]:
    with backend:
        backend.connect(device_ref)
        raw = backend.read_token()

    if raw is None:
        result = VerificationResult.NOT_REGISTERED
        detail = "no token found on device"
        db.append_log(conn, "verify", None, result.value, detail)
        return result, detail

    try:
        candidate = token_mod.RegistrationToken.from_wire_string(raw)
    except Exception as exc:
        result = VerificationResult.TAMPER_SUSPECTED
        detail = f"token unparsable: {exc}"
        db.append_log(conn, "verify", None, result.value, detail)
        return result, detail

    if not token_mod.verify_token(candidate, public_key):
        result = VerificationResult.TAMPER_SUSPECTED
        detail = "signature verification failed"
        db.append_log(conn, "verify", candidate.printer_id, result.value, detail)
        return result, detail

    if not db.is_printer_registered(conn, candidate.printer_id):
        result = VerificationResult.TAMPER_SUSPECTED
        detail = "signature valid but printer_id not found in local snapshot"
        db.append_log(conn, "verify", candidate.printer_id, result.value, detail)
        return result, detail

    result = VerificationResult.REGISTERED
    detail = f"matched printer_id={candidate.printer_id}"
    db.append_log(conn, "verify", candidate.printer_id, result.value, detail)
    return result, detail
