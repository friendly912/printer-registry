"""Byte-level transport to a printer, abstracted so the PJL backend can run
against either a real USB printer device file or a fake device in tests.
"""
from __future__ import annotations

import os
import select
from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None:
        ...

    @abstractmethod
    def read(self, max_bytes: int = 4096, timeout: float = 2.0) -> bytes:
        """Read up to max_bytes, waiting at most timeout seconds. Returns
        b"" on timeout (some devices simply don't answer, e.g. a variable
        that was never set)."""

    @abstractmethod
    def close(self) -> None:
        ...


class TransportTimeout(RuntimeError):
    pass


class USBPrinterFileTransport(Transport):
    """Talks to a USB printer exposed by the kernel as a character device
    (e.g. /dev/usb/lp0 on Linux). This is the real-hardware implementation:
    point it at the actual device path once a printer is connected.
    """

    def __init__(self, device_path: str):
        self._device_path = device_path
        self._fd: int | None = None

    def open(self) -> None:
        self._fd = os.open(self._device_path, os.O_RDWR)

    def write(self, data: bytes) -> None:
        if self._fd is None:
            raise RuntimeError("transport not open")
        os.write(self._fd, data)

    def read(self, max_bytes: int = 4096, timeout: float = 2.0) -> bytes:
        if self._fd is None:
            raise RuntimeError("transport not open")
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return b""
        return os.read(self._fd, max_bytes)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class SocketTransport(Transport):
    """Wraps a connected socket. Used to drive the backend against a fake
    in-process "printer" over a real socketpair() in tests -- same
    write()/read() contract a real device file would satisfy.
    """

    def __init__(self, sock):
        self._sock = sock

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def read(self, max_bytes: int = 4096, timeout: float = 2.0) -> bytes:
        self._sock.settimeout(timeout)
        try:
            return self._sock.recv(max_bytes)
        except OSError:
            return b""

    def close(self) -> None:
        self._sock.close()
