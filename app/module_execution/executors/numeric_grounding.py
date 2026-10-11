"""Exact, indivisible numerical context, never numeric entailment by token overlap."""
import re
from collections.abc import Mapping

from .common import NumericLocation, SemanticRule, StatementSemanticsError
from .claim_support import strategy_claim, assertion_support


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
    """Context propagation is separate from downstream assertion authority."""
    parsed = strategy_claim(value)
    if parsed is not None:
        yield from context_units(parsed.summary)
        yield from context_units(parsed.items)
        for context in parsed.numeric_context:
            yield from context_units(context.quote)
    else:
        for text in assertion_support(value):
            yield from context_units(text)


def context_attribution(context, local, parents):
    if context.support_id in local:
        evidence = local[context.support_id]
        is_site = (evidence.input_key == "site_claim" or
                   isinstance(evidence.value, Mapping) and evidence.value.get("trust") == "site_claim")
        return "site_claim" if is_site else "supplied_context"
    parsed = strategy_claim(parents[context.support_id].value)
    if parsed is not None:
        matches = [c.attribution for c in parsed.numeric_context if c.quote == context.quote]
        # Conflicting/legacy attribution must never imply owner confirmation.
        return matches[0] if matches and len(set(matches)) == 1 else "unknown"
    return "parent_claim"
