"""Exercises PJLUSBBackend's real protocol encoding/decoding against a fake
in-process "printer" connected over a genuine socketpair() -- no physical
hardware needed, but the bytes actually cross a socket and get parsed as a
real device's response would be.
"""
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printer_registry.pjl_protocol import UEL
from printer_registry.pjl_usb_backend import PJLUSBBackend
from printer_registry.transport import SocketTransport


def fake_printer_loop(sock: socket.socket, store: dict, stop_event: threading.Event) -> None:
    """Minimal PJL device simulator: understands @PJL DEFAULT (persist) and
    @PJL DINQUIRE (read back)."""
    buffer = b""
    while not stop_event.is_set():
        sock.settimeout(0.5)
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        text = buffer.replace(UEL, b"").decode("utf-8", errors="ignore")
        buffer = b""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("@PJL DEFAULT "):
                rest = line[len("@PJL DEFAULT "):]
                if "=" in rest:
                    var, val = rest.split("=", 1)
                    val = val.strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1].replace('\\"', '"')
                    store[var] = val
            elif line.startswith("@PJL DINQUIRE "):
                var = line[len("@PJL DINQUIRE "):].strip()
                if var in store:
                    resp = f'@PJL DINQUIRE {var}\r\n"{store[var]}"\r\n'.encode("utf-8")
                else:
                    resp = f"@PJL DINQUIRE {var}\r\n?PJL DINQUIRE : VARIABLE NOT FOUND\r\n".encode("utf-8")
                try:
                    sock.sendall(resp)
                except OSError:
                    break


class TestPJLUSBBackend(unittest.TestCase):
    """Each _make_backend() call opens a fresh socketpair + fake-printer
    thread, mirroring how a real connect() opens a fresh handle to
    /dev/usb/lpX each time. All sessions share self.store, standing in for
    the printer's own persistent NVRAM surviving across reconnects.
    """

    def setUp(self):
        self.store: dict = {}
        self._sessions: list[tuple[socket.socket, threading.Thread, threading.Event]] = []

    def tearDown(self):
        for printer_sock, thread, stop_event in self._sessions:
            stop_event.set()
            try:
                printer_sock.close()
            except OSError:
                pass
            thread.join(timeout=2)

    def _make_backend(self) -> PJLUSBBackend:
        backend_sock, printer_sock = socket.socketpair()
        stop_event = threading.Event()
        thread = threading.Thread(
            target=fake_printer_loop,
            args=(printer_sock, self.store, stop_event),
            daemon=True,
        )
        thread.start()
        self._sessions.append((printer_sock, thread, stop_event))

        def factory(_device_ref: str):
            return SocketTransport(backend_sock)

        return PJLUSBBackend(transport_factory=factory)

    def test_write_then_read_round_trip(self):
        writer = self._make_backend()
        with writer:
            writer.connect("fake:0")
            writer.write_token('{"token_id":"abc-123","printer_id":"p1"}')

        reader = self._make_backend()
        with reader:
            reader.connect("fake:0")
            result = reader.read_token()

        self.assertEqual(result, '{"token_id":"abc-123","printer_id":"p1"}')

    def test_read_before_write_returns_none(self):
        reader = self._make_backend()
        with reader:
            reader.connect("fake:0")
            result = reader.read_token()
        self.assertIsNone(result)

    def test_token_with_embedded_quotes_round_trips(self):
        tricky = 'contains "quotes" and a backslash \\ here'
        writer = self._make_backend()
        with writer:
            writer.connect("fake:0")
            writer.write_token(tricky)

        reader = self._make_backend()
        with reader:
            reader.connect("fake:0")
            result = reader.read_token()
        self.assertEqual(result, tricky)


if __name__ == "__main__":
    unittest.main()
