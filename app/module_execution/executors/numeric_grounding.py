"""Exact, indivisible numerical context, never numeric entailment by token overlap."""
import json
import re
from collections.abc import Mapping

from .common import NumericLocation, SemanticRule, StatementSemanticsError


def context_units(value):
    """Only complete textual leaves retain their assertion and qualifiers.

    Bare scalar numbers/number strings lack units and relationships. They cannot
    be combined with keys, other leaves or another source into a new assertion.
    No sentence splitting, normalization, substring matching or calculations.
    """
    if isinstance(value, str):
        if (1 <= len(value) <= 1000 and re.search(r"\d", value)
                and re.search(r"[^\W\d_]", value) and value == value.strip()):
            yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from context_units(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from context_units(child)


def validate_numeric_context(statement, local, parents):
    for location, texts in ((NumericLocation.TEXT, [statement.text]),
                            (NumericLocation.ITEMS, statement.items)):
        for text in texts:
            if re.search(r"\d", text):
                raise StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
                                              numeric_location=location)
    for context in getattr(statement, "numeric_context", ()):
        identity = context.support_id
        if identity in statement.evidence_ids and identity in local:
            units = context_units(local[identity].value)
        elif identity in statement.parent_claim_ids and identity in parents:
            units = parent_context_units(parents[identity].value)
        else:
            units = ()
        if context.quote not in tuple(units):
            raise StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
                                          numeric_location=NumericLocation.CONTEXT)


def parent_context_units(value):
    """Read the authoritative CMO claim envelope without quoting technical IDs.

    A plain parent assertion is indivisible. A structured CMO claim carries
    separately validated textual units; only those units can propagate as quoted
    context. Other serialized structures cannot be reinterpreted as assertions.
    """
    if not isinstance(value, str):
        return
    try:
        parsed = json.loads(value)
    except (ValueError, RecursionError):
        if not value.lstrip().startswith(("{", "[")):
            yield from context_units(value)
        return
    if not isinstance(parsed, (dict, list)):
        yield from context_units(value)
        return
    if (not isinstance(parsed, dict)
            or set(parsed) not in ({"summary", "items"}, {"summary", "items", "numeric_context"})
            or not isinstance(parsed["summary"], str)
            or not isinstance(parsed["items"], list)
            or not all(isinstance(item, str) for item in parsed["items"])):
        return
    yield from context_units(parsed["summary"])
    yield from context_units(parsed["items"])
    contexts = parsed.get("numeric_context", [])
    if not isinstance(contexts, list):
        return
    for context in contexts:
        if (isinstance(context, dict) and set(context) == {"support_id", "quote"}
                and isinstance(context["support_id"], str) and isinstance(context["quote"], str)):
            yield from context_units(context["quote"])
