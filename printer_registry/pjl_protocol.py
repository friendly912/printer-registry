"""PJL (Printer Job Language) command encoding/decoding.

This is the generic baseline: `@PJL DEFAULT <var>=<value>` to persist a
variable to NVRAM, and `@PJL DINQUIRE <var>` to read it back. Real vendors
diverge here -- some require `@PJL SET` instead of `@PJL DEFAULT` for
persistence, some wrap the query differently, some need a vendor-specific
"enter maintenance mode" command first. Treat this module as the template a
per-vendor adapter overrides, not a drop-in for every printer.

Kept free of any actual I/O so it can be unit tested byte-for-byte without
hardware.
"""
from __future__ import annotations

from typing import Optional

UEL = b"\x1b%-12345X"  # Universal Exit Language: switches the device into/out of PJL mode
FORM_FEED = b"\x0c"


def build_set_command(var_name: str, value: str) -> bytes:
    """Persist var_name=value to the device's NVRAM."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    body = f'@PJL DEFAULT {var_name}="{escaped}"\r\n'
    return UEL + body.encode("utf-8") + UEL


def build_dinquire_command(var_name: str) -> bytes:
    """Ask the device for the current value of var_name."""
    body = f"@PJL DINQUIRE {var_name}\r\n"
    return UEL + body.encode("utf-8") + UEL


def parse_dinquire_response(raw: bytes) -> Optional[str]:
    """Extract the quoted value from a DINQUIRE response, or None if the
    variable isn't set / the device reported an error (leading '?').
    """
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("@PJL") or line.startswith("?"):
            continue
        if line.startswith('"') and line.endswith('"') and len(line) >= 2:
            unescaped = line[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            return unescaped
    return None
