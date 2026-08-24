from __future__ import annotations

from functools import lru_cache
import hashlib
from importlib.resources import files
import re


EXPERT_CORE_VERSION = "1.0.0"
_SEMANTIC_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RESOURCE_BY_VERSION = {
    EXPERT_CORE_VERSION: "v1.0.0.md",
}
_NORMALIZED_SHA256_BY_VERSION = {
    EXPERT_CORE_VERSION: "5dad2b61b14c6a137668bd7ed0a5ee3b5cff45235d7c79726337b1e3529d72f9",
}


class ExpertCoreResourceError(RuntimeError):
    """Raised when the canonical Expert Core resource cannot be loaded safely."""


def normalize_expert_core(content: str) -> str:
    if not isinstance(content, str):
        raise ExpertCoreResourceError("Expert Core resource must be text")
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip(" \t") for line in normalized.split("\n"))
    return normalized.rstrip("\n")


def normalized_expert_core_sha256(content: str) -> str:
    normalized = normalize_expert_core(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_expert_core(content: str, version: str = EXPERT_CORE_VERSION) -> str:
    expected_checksum = _NORMALIZED_SHA256_BY_VERSION.get(version)
    if expected_checksum is None:
        raise ExpertCoreResourceError(f"Unsupported Expert Core version: {version}")

    normalized = normalize_expert_core(content)
    if not normalized.strip():
        raise ExpertCoreResourceError(
            f"Expert Core resource is empty for version {version}"
        )
    actual_checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual_checksum != expected_checksum:
        raise ExpertCoreResourceError(
            f"Expert Core resource checksum mismatch for version {version}"
        )
    return normalized


@lru_cache(maxsize=None)
def load_expert_core(version: str = EXPERT_CORE_VERSION) -> str:
    if not _SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ExpertCoreResourceError(f"Invalid Expert Core version: {version!r}")

    filename = _RESOURCE_BY_VERSION.get(version)
    if filename is None:
        raise ExpertCoreResourceError(f"Unsupported Expert Core version: {version}")

    resource = files(__package__).joinpath(filename)
    try:
        content = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ExpertCoreResourceError(
            f"Expert Core resource is unavailable for version {version}"
        ) from exc

    return validate_expert_core(content, version)


__all__ = [
    "EXPERT_CORE_VERSION",
    "ExpertCoreResourceError",
    "load_expert_core",
    "normalize_expert_core",
    "normalized_expert_core_sha256",
    "validate_expert_core",
]
