"""Canonical email subjects shared by credential and verified identity operations."""
import re

_ATOM = r"[a-z0-9!#$%&'*+/=?^_{}|~\x60-]+"
_LOCAL = re.compile(rf"{_ATOM}(?:\.{_ATOM})*")
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")


def normalize_email(address: str) -> str:
    if not address.isascii() or len(address) > 254:
        raise ValueError("invalid email address")
    normalized = address.lower()
    local, separator, domain = normalized.partition("@")
    if not separator or len(local) > 64 or not _LOCAL.fullmatch(local) or not _DOMAIN.fullmatch(domain):
        raise ValueError("invalid email address")
    return normalized
