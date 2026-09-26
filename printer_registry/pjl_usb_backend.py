"""Real-hardware PrinterBackend implementation: talks PJL over a USB
printer device file. This is the piece that replaces MockPrinterBackend
once actual printers are available to test against.

The variable name chosen for the registration token (REGTOKEN) is
arbitrary and will very likely collide with vendor-reserved names on real
devices -- confirm a safe custom-variable namespace per vendor before
deploying this beyond a lab test.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import pjl_protocol
from .printer_iface import PrinterBackend
from .transport import Transport, USBPrinterFileTransport

REGISTRATION_VARIABLE = "REGTOKEN"

TransportFactory = Callable[[str], Transport]


def _default_transport_factory(device_ref: str) -> Transport:
    transport = USBPrinterFileTransport(device_ref)
    transport.open()
    return transport


class PJLUSBBackend(PrinterBackend):
    def __init__(self, transport_factory: Optional[TransportFactory] = None):
        self._transport_factory = transport_factory or _default_transport_factory
        self._transport: Optional[Transport] = None

    def connect(self, device_ref: str) -> None:
        self._transport = self._transport_factory(device_ref)

    def write_token(self, raw_token: str) -> None:
        assert self._transport is not None, "connect() must be called first"
        command = pjl_protocol.build_set_command(REGISTRATION_VARIABLE, raw_token)
        self._transport.write(command)

    def read_token(self) -> Optional[str]:
        assert self._transport is not None, "connect() must be called first"
        command = pjl_protocol.build_dinquire_command(REGISTRATION_VARIABLE)
        self._transport.write(command)
        raw = self._transport.read()
        return pjl_protocol.parse_dinquire_response(raw)

    def disconnect(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
