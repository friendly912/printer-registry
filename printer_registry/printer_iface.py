"""Pluggable printer-communication layer.

Phase 0 has no physical printer/USB hardware to test against, so the only
implementation here is MockPrinterBackend, which simulates a device's NVRAM
as an in-memory (or on-disk JSON) store. A real deployment swaps this out
for a vendor-specific adapter (PJL-over-USB, SNMP private MIB, EWS API,
etc.) that implements the same PrinterBackend interface -- nothing above
this layer needs to change.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class PrinterBackend(ABC):
    """Contract every vendor adapter (real or simulated) must satisfy."""

    @abstractmethod
    def connect(self, device_ref: str) -> None:
        """Establish a connection to the physical device (e.g. open a USB handle)."""

    @abstractmethod
    def write_token(self, raw_token: str) -> None:
        """Write the token's wire string into the device's NVRAM / custom storage."""

    @abstractmethod
    def read_token(self) -> Optional[str]:
        """Read back the token's wire string, or None if nothing is stored."""

    @abstractmethod
    def disconnect(self) -> None:
        ...

    def __enter__(self) -> "PrinterBackend":
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()


class PrinterNotFoundError(RuntimeError):
    pass


class MockPrinterBackend(PrinterBackend):
    """Simulates NVRAM as a JSON file keyed by device_ref (stand-in for a
    USB device path / serial number). Lets the rest of the system be
    exercised end-to-end without real hardware.
    """

    def __init__(self, store_path: Path):
        self._store_path = store_path
        self._device_ref: Optional[str] = None
        if not self._store_path.exists():
            self._store_path.write_text("{}")

    def _load_store(self) -> dict:
        return json.loads(self._store_path.read_text())

    def _save_store(self, store: dict) -> None:
        self._store_path.write_text(json.dumps(store, indent=2))

    def connect(self, device_ref: str) -> None:
        self._device_ref = device_ref

    def write_token(self, raw_token: str) -> None:
        assert self._device_ref is not None, "connect() must be called first"
        store = self._load_store()
        store[self._device_ref] = raw_token
        self._save_store(store)

    def read_token(self) -> Optional[str]:
        assert self._device_ref is not None, "connect() must be called first"
        store = self._load_store()
        return store.get(self._device_ref)

    def disconnect(self) -> None:
        self._device_ref = None
