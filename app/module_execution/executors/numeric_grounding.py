"""Exact, indivisible numerical context, never numeric entailment by token overlap."""
import json
import re
from collections.abc import Mapping
from copy import deepcopy

from pydantic import ValidationError

from .intelligence_schemas import NumericContext
from .schemas import OutputStatement

from .common import NumericLocation, NumericContextFailureReason, SemanticRule, StatementSemanticsError
from .claim_support import strategy_claim, assertion_support
from .numeric_quantity import has_numeric_quantity


def context_units(value):
    """Only complete textual leaves retain their assertion and qualifiers.

    Bare scalar numbers/number strings lack units and relationships. They cannot
    be combined with keys, other leaves or another source into a new assertion.
    No sentence splitting, normalization, substring matching or calculations.
    """
    if isinstance(value, str):
        if (1 <= len(value) <= 1000 and has_numeric_quantity(value)
                and re.search(r"[^\W\d_]", value) and value == value.strip()):
            yield value
    elif isinstance(value, Mapping):
        if value.get("trust") == "site_claim":
            # The owned-site projection carries IDs/evidence metadata alongside
            # its assertion text. Only site_states is a quotation channel.
            yield from context_units(value.get("site_states", ()))
            return
        for child in value.values():
            yield from context_units(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from context_units(child)


def validate_numeric_context(statement, local, parents):
    for location, texts in ((NumericLocation.TEXT, [statement.text]),
                            (NumericLocation.ITEMS, statement.items)):
        for text in texts:
            if has_numeric_quantity(text):
                raise StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
                                              numeric_location=location)
    for index, context in enumerate(getattr(statement, "numeric_context", ())):
        identity = context.support_id
        # Classify only the condition actually checked; earlier schema/support
        # failures keep their own stages and are never reclassified here.
        if identity not in local and identity not in parents:
            reason = NumericContextFailureReason.SUPPORT_NOT_FOUND
        elif identity in statement.evidence_ids and identity in local:
            reason = quote_failure_reason(context.quote, tuple(context_units(local[identity].value)))
        elif identity in statement.parent_claim_ids and identity in parents:
            reason = quote_failure_reason(context.quote, tuple(parent_context_units(parents[identity].value)))
        else:
            reason = NumericContextFailureReason.SUPPORT_NOT_CITED
        if reason is not None:
            raise StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
                numeric_location=NumericLocation.CONTEXT, numeric_context_reason=reason,
                numeric_context_index=index)


def quote_failure_reason(quote, units):
    if quote in units:
        return None
    if not units:
        return NumericContextFailureReason.SOURCE_HAS_NO_ELIGIBLE_QUOTE
    if type(quote) is not str or not quote:
        return NumericContextFailureReason.OTHER_NUMERIC_CONTEXT_INVALID
    if any(quote in unit for unit in units):
        return NumericContextFailureReason.QUOTE_IS_FRAGMENT
    return NumericContextFailureReason.QUOTE_NOT_EXACT


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


def bind_numeric_context_citations(payload, local, parents):
    """Append only raw model-selected, exact-source references; never infer support.

    Input has passed the original schema and Pydantic. Work on raw JSON so their
    whitespace handling cannot authorize a newly bound quote. Each statement's
    additions are atomic; invalid/ambiguous sources, duplicate references, missing
    mandatory parents or exceeded bounds are left for the original pipeline to
    reject. The returned count records bindings, not acceptance or gate success.
    """
    candidate = deepcopy(payload)
    count = 0
    for statement in candidate["outputs"]:
        if parents and not statement["parent_claim_ids"]:
            continue
        if any(len(ids) != len(set(ids)) for ids in
               (statement["evidence_ids"], statement["parent_claim_ids"])):
            continue
        additions = {"evidence_ids": [], "parent_claim_ids": []}
        for context in statement["numeric_context"]:
            identity, quote = context["support_id"], context["quote"]
            # Cross-family collisions have no unambiguous attribution channel.
            if (identity in local) == (identity in parents):
                break
            if identity in local:
                field, units = "evidence_ids", context_units(local[identity].value)
            else:
                field, units = "parent_claim_ids", parent_context_units(parents[identity].value)
            if quote not in tuple(units):
                break
            if identity not in statement[field] and identity not in additions[field]:
                additions[field].append(identity)
        else:
            updated = {**statement, **{field: statement[field] + ids for field, ids in additions.items()}}
            try:
                # Inherit authoritative reference bounds, never truncate arrays.
                OutputStatement.model_validate({key: value for key, value in updated.items()
                                                if key not in ("items", "numeric_context")})
            except ValidationError:
                continue
            added = sum(map(len, additions.values()))
            if added:
                statement.update(updated)
                count += added
    return (candidate, count) if count else (payload, 0)


MAX_NUMERIC_QUOTE_CATALOG_ENTRIES = 64
MAX_NUMERIC_QUOTE_CATALOG_BYTES = 16384


def numeric_quote_catalog(local, parents):
    """Bounded deterministic hints from the validator's exact quotation channels.

    Caller supplies only request-local evidence and accepted scoped parents.
    Whole entries are skipped when they cannot fit; no truncation or rewriting.
    The byte limit includes JSON escaping, identities, keys and list overhead.
    """
    catalog = []
    size = 2  # JSON list brackets
    for identity, source, extractor in sorted(
            [(identity, e.value, context_units) for identity, e in local.items()]
            + [(identity, p.value, parent_context_units) for identity, p in parents.items()],
            key=lambda item: item[0]):
        if type(identity) is not str or not 1 <= len(identity) <= 128:
            continue
        for quote in sorted(set(extractor(source))):
            try:
                NumericContext(support_id=identity, quote=quote)
            except ValidationError:
                continue
            entry = {"support_id": identity, "exact_quote": quote}
            if entry in catalog:
                continue
            try:
                entry_size = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            except UnicodeError:
                continue
            addition = entry_size + (2 if catalog else 0)
            if size + addition > MAX_NUMERIC_QUOTE_CATALOG_BYTES:
                continue
            catalog.append(entry)
            size += addition
            if len(catalog) == MAX_NUMERIC_QUOTE_CATALOG_ENTRIES:
                return catalog
    return catalog
