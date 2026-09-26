"""End-to-end test of the Phase 0 PoC flow against the mock printer backend:
register -> verify (registered) -> tamper -> verify (tamper_suspected) ->
verify unknown device (not_registered) -> log chain integrity.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile
import unittest

from printer_registry import crypto, db
from printer_registry.judge import VerificationResult, verify_printer
from printer_registry.printer_iface import MockPrinterBackend
from printer_registry.token import issue_token, RegistrationToken


class TestPhase0Flow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        self.private_key_path = base / "priv.pem"
        self.public_key_path = base / "pub.pem"
        crypto.generate_keypair(self.private_key_path, self.public_key_path)
        self.private_key = crypto.load_private_key(self.private_key_path)
        self.public_key = crypto.load_public_key(self.public_key_path)

        self.db_path = base / "terminal.sqlite3"
        self.conn = db.connect(self.db_path)
        self.nvram_path = base / "mock_nvram.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _backend(self):
        return MockPrinterBackend(self.nvram_path)

    def test_register_then_verify_is_registered(self):
        printer_id = "printer-abc123"
        tok = issue_token(printer_id, "issuer-1", self.private_key)
        with self._backend() as backend:
            backend.connect("usb:001")
            backend.write_token(tok.to_wire_string())
        db.register_printer(self.conn, printer_id, "ModelX", "Floor 3")
        db.store_token(self.conn, printer_id, tok.token_id, tok.issued_at, tok.issuer_id, tok.signature_hex)

        result, detail = verify_printer(self._backend(), "usb:001", self.public_key, self.conn)
        self.assertEqual(result, VerificationResult.REGISTERED)

    def test_unregistered_device_has_no_token(self):
        result, detail = verify_printer(self._backend(), "usb:999-never-registered", self.public_key, self.conn)
        self.assertEqual(result, VerificationResult.NOT_REGISTERED)

    def test_tampered_signature_is_detected(self):
        printer_id = "printer-def456"
        tok = issue_token(printer_id, "issuer-1", self.private_key)
        with self._backend() as backend:
            backend.connect("usb:002")
            backend.write_token(tok.to_wire_string())
        db.register_printer(self.conn, printer_id, "ModelY", "Floor 1")
        db.store_token(self.conn, printer_id, tok.token_id, tok.issued_at, tok.issuer_id, tok.signature_hex)

        # simulate tampering: flip a field after the token was written
        with self._backend() as backend:
            backend.connect("usb:002")
            raw = backend.read_token()
            corrupted = RegistrationToken(
                token_id=tok.token_id,
                printer_id=tok.printer_id,
                issued_at=tok.issued_at,
                issuer_id="attacker-issuer",  # changed after signing
                signature_hex=tok.signature_hex,  # stale signature
            )
            backend.write_token(corrupted.to_wire_string())

        result, detail = verify_printer(self._backend(), "usb:002", self.public_key, self.conn)
        self.assertEqual(result, VerificationResult.TAMPER_SUSPECTED)

    def test_forged_key_is_rejected(self):
        # a token signed by a DIFFERENT private key must not verify against
        # this terminal's trusted public key
        other_priv_path = Path(self.tmpdir.name) / "other_priv.pem"
        other_pub_path = Path(self.tmpdir.name) / "other_pub.pem"
        crypto.generate_keypair(other_priv_path, other_pub_path)
        other_private_key = crypto.load_private_key(other_priv_path)

        printer_id = "printer-ghi789"
        forged_tok = issue_token(printer_id, "rogue-issuer", other_private_key)
        with self._backend() as backend:
            backend.connect("usb:003")
            backend.write_token(forged_tok.to_wire_string())
        db.register_printer(self.conn, printer_id, "ModelZ", "Floor 2")

        result, detail = verify_printer(self._backend(), "usb:003", self.public_key, self.conn)
        self.assertEqual(result, VerificationResult.TAMPER_SUSPECTED)

    def test_log_chain_detects_manual_row_edit(self):
        db.append_log(self.conn, "register", "printer-abc123", "registered", "seed")
        db.append_log(self.conn, "verify", "printer-abc123", "registered", "check")
        self.assertTrue(db.verify_log_chain(self.conn))

        # simulate an operator editing a log row directly in the DB
        self.conn.execute("UPDATE operation_log SET detail = 'edited' WHERE seq = 1")
        self.conn.commit()
        self.assertFalse(db.verify_log_chain(self.conn))


if __name__ == "__main__":
    unittest.main()
