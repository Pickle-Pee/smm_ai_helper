"""Server-owned decoding of persisted strategy claims, with separate authority channels."""
import json
from typing import Literal

from pydantic import ConfigDict, Field

from .schemas import StrictOutput, Text
from .numeric_quantity import has_numeric_quantity
from .intelligence_schemas import NumericContext, ShortText


class StoredNumericContext(NumericContext):
    model_config = ConfigDict(**{**NumericContext.model_config, "str_strip_whitespace": False})
    # Assigned by the executor, never requested from the provider. Legacy quotes
    # have unknown attribution and cannot become owner-confirmed facts.
    attribution: Literal["site_claim", "supplied_context", "parent_claim", "unknown"] = "unknown"


class StrategyClaim(StrictOutput):
    model_config = ConfigDict(**{**StrictOutput.model_config, "str_strip_whitespace": False})
    summary: Text
    items: list[ShortText] = Field(min_length=1, max_length=3)
    numeric_context: list[StoredNumericContext] = Field(default_factory=list, max_length=3)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate claim field")
        result[key] = value
    return result


def strategy_claim(value):
    """Unknown/malformed serialized structures provide no assertion support."""
    if not isinstance(value, str) or len(value) > 16000:
        return None
    try:
        return StrategyClaim.model_validate(json.loads(value, object_pairs_hook=unique_object))
    except (ValueError, RecursionError):
        return None


def assertion_support(value):
    """Never expose JSON, contextual quotes or identities as assertion text.

    Plain accepted assertions retain existing numeric authority. Strategy
    envelopes expose qualitative summaries/actions only; contextual numbers,
    including those in legacy envelopes, confer no downstream numeric authority.
    """
    if not isinstance(value, str):
        return ()
    if value.lstrip().startswith(("{", "[")):
        parsed = strategy_claim(value)
        return tuple(t for t in (parsed.summary, *parsed.items) if not has_numeric_quantity(t)) if parsed else ()
    return (value,)
