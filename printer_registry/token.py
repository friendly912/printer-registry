"""Registration token: the payload written to a printer's NVRAM / driver
storage and later read back for verification.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey, EllipticCurvePublicKey

from . import crypto


@dataclass(frozen=True)
class RegistrationToken:
    token_id: str
    printer_id: str  # hashed serial number, not the raw serial
    issued_at: str
    issuer_id: str
    signature_hex: str = ""

    def signing_payload(self) -> bytes:
        """Canonical bytes that get signed / verified (excludes the signature itself)."""
        fields = {
            "token_id": self.token_id,
            "printer_id": self.printer_id,
            "issued_at": self.issued_at,
            "issuer_id": self.issuer_id,
        }
        return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_wire_string(self) -> str:
        """Compact string actually written to the printer's storage."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_wire_string(raw: str) -> "RegistrationToken":
        return RegistrationToken(**json.loads(raw))


def issue_token(printer_id: str, issuer_id: str, private_key: EllipticCurvePrivateKey) -> RegistrationToken:
    unsigned = RegistrationToken(
        token_id=str(uuid.uuid4()),
        printer_id=printer_id,
        issued_at=datetime.now(timezone.utc).isoformat(),
        issuer_id=issuer_id,
    )
    signature = crypto.sign(private_key, unsigned.signing_payload())
    return RegistrationToken(
        token_id=unsigned.token_id,
        printer_id=unsigned.printer_id,
        issued_at=unsigned.issued_at,
        issuer_id=unsigned.issuer_id,
        signature_hex=signature.hex(),
    )


def verify_token(token: RegistrationToken, public_key: EllipticCurvePublicKey) -> bool:
    if not token.signature_hex:
        return False
    signature = bytes.fromhex(token.signature_hex)
    return crypto.verify(public_key, token.signing_payload(), signature)
