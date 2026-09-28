"""Tests for batch registration: multiple devices detected/registered in
one pass, idempotency on a second run, and refusal to silently overwrite a
device whose stored token fails verification.
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printer_registry import crypto, db
from printer_registry.batch_register import Outcome, discover_devices, load_metadata_csv, register_batch
from printer_registry.printer_iface import MockPrinterBackend
from printer_registry.token import RegistrationToken, issue_token


class TestDiscoverDevices(unittest.TestCase):
    def test_globs_device_files_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ["lp1", "lp0", "lp2", "other"]:
                (base / name).touch()

            found = discover_devices(str(base / "lp*"))
            self.assertEqual(found, [str(base / "lp0"), str(base / "lp1"), str(base / "lp2")])

    def test_no_matches_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = discover_devices(str(Path(tmp) / "lp*"))
            self.assertEqual(found, [])


class TestLoadMetadataCsv(unittest.TestCase):
    def test_parses_rows_into_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "devices.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["device_ref", "model", "location"])
                writer.writerow(["usb:001", "Canon X1", "本社3F"])
                writer.writerow(["usb:002", "Epson E1", "倉庫1F"])

            metadata = load_metadata_csv(csv_path)
            self.assertEqual(metadata["usb:001"], {"model": "Canon X1", "location": "本社3F"})
            self.assertEqual(metadata["usb:002"], {"model": "Epson E1", "location": "倉庫1F"})


class TestRegisterBatch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        base = Path(self.tmpdir.name)
        crypto.generate_keypair(base / "priv.pem", base / "pub.pem")
        self.private_key = crypto.load_private_key(base / "priv.pem")
        self.public_key = crypto.load_public_key(base / "pub.pem")
        self.conn = db.connect(base / "terminal.sqlite3")
        self.nvram_path = base / "mock_nvram.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _backend_factory(self):
        return MockPrinterBackend(self.nvram_path)

    def test_registers_multiple_new_devices_in_one_pass(self):
        device_refs = ["usb:001", "usb:002", "usb:003"]
        metadata = {"usb:001": {"model": "Canon X1", "location": "本社3F"}}

        results = register_batch(
            device_refs, metadata, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )

        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r.outcome, Outcome.REGISTERED)
            self.assertIsNotNone(r.printer_id)

        row = self.conn.execute(
            "SELECT model, location FROM printers WHERE printer_id = ?", (results[0].printer_id,)
        ).fetchone()
        self.assertEqual(row, ("Canon X1", "本社3F"))

        # device with no CSV entry falls back to the defaults
        row2 = self.conn.execute(
            "SELECT model, location FROM printers WHERE printer_id = ?", (results[1].printer_id,)
        ).fetchone()
        self.assertEqual(row2, ("unknown", "unknown"))

    def test_second_pass_is_idempotent(self):
        device_refs = ["usb:001", "usb:002"]
        first = register_batch(
            device_refs, {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )
        self.assertTrue(all(r.outcome == Outcome.REGISTERED for r in first))

        second = register_batch(
            device_refs, {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )
        self.assertTrue(all(r.outcome == Outcome.ALREADY_REGISTERED for r in second))
        # printer_id should match what the first pass assigned
        self.assertEqual({r.printer_id for r in first}, {r.printer_id for r in second})

    def test_tampered_device_is_flagged_and_left_untouched(self):
        device_refs = ["usb:001"]
        first = register_batch(
            device_refs, {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )
        original_printer_id = first[0].printer_id

        # simulate tampering: overwrite the stored token with a stale-signature version
        with self._backend_factory() as backend:
            backend.connect("usb:001")
            raw = backend.read_token()
            original = RegistrationToken.from_wire_string(raw)
            corrupted = RegistrationToken(
                token_id=original.token_id,
                printer_id=original.printer_id,
                issued_at=original.issued_at,
                issuer_id="attacker-issuer",
                signature_hex=original.signature_hex,
            )
            backend.write_token(corrupted.to_wire_string())

        second = register_batch(
            device_refs, {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )
        self.assertEqual(second[0].outcome, Outcome.NEEDS_REVIEW)

        # the DB record must be untouched -- batch registration must not
        # silently overwrite a device flagged as tamper_suspected
        row = self.conn.execute(
            "SELECT printer_id FROM printers WHERE printer_id = ?", (original_printer_id,)
        ).fetchone()
        self.assertIsNotNone(row)

    def test_mixed_batch_new_and_already_registered(self):
        register_batch(
            ["usb:001"], {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )

        results = register_batch(
            ["usb:001", "usb:002"], {}, "unknown", "unknown",
            self.private_key, self.public_key, self.conn, self._backend_factory, "issuer-1",
        )
        outcomes = {r.device_ref: r.outcome for r in results}
        self.assertEqual(outcomes["usb:001"], Outcome.ALREADY_REGISTERED)
        self.assertEqual(outcomes["usb:002"], Outcome.REGISTERED)


if __name__ == "__main__":
    unittest.main()
