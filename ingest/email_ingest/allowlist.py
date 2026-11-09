from __future__ import annotations

import re
from email.utils import parseaddr


_ANGLE_ADDR = re.compile(r"<([^>]+)>")


def extract_from_address(from_header: str | None) -> str:
    """Return the bare email address from a From header, lowercased."""
    if not from_header:
        return ""
    _, addr = parseaddr(from_header)
    if addr:
        return addr.strip().lower()
    match = _ANGLE_ADDR.search(from_header)
    if match:
        return match.group(1).strip().lower()
    return from_header.strip().lower()


def is_allowlisted(from_header: str | None, allowlist: frozenset[str]) -> bool:
    address = extract_from_address(from_header)
    if not address:
        return False
    return address in allowlist
