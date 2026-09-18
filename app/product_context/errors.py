"""Safe, caller-visible capability outcomes; never raw transport/provider errors."""
from enum import Enum


class SourceOutcome(str, Enum):
    ACQUIRED = "ACQUIRED"
    UNSAFE_SOURCE = "UNSAFE_SOURCE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    INVALID_EXTRACTION = "INVALID_EXTRACTION"


class ProductContextError(ValueError):
    """Invalid caller contract or unsupported evidence linkage."""
