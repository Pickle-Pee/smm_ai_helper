from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import re


EXPERT_CORE_VERSION = "1.0.0"
_SEMANTIC_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_RESOURCE_BY_VERSION = {
    EXPERT_CORE_VERSION: "v1.0.0.md",
}


class ExpertCoreResourceError(RuntimeError):
    """Raised when the canonical Expert Core resource cannot be loaded safely."""


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

    content = content.lstrip("\ufeff").strip()
    if not content:
        raise ExpertCoreResourceError(
            f"Expert Core resource is empty for version {version}"
        )
    return content


__all__ = [
    "EXPERT_CORE_VERSION",
    "ExpertCoreResourceError",
    "load_expert_core",
]
