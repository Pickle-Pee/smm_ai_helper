"""Request-local observations only. Never participates in numerical acceptance."""
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
import json
import logging
import unicodedata

from .common import SemanticRule, StatementSemanticsError
from .numeric_grounding import context_units, parent_context_units

log = logging.getLogger(__name__)
POLICY_VERSION = "numeric_diagnostics.v1"
MAX_SOURCES = 64
MAX_NODES = 2048
MAX_CHARACTERS = 65536
MAX_DEPTH = 32
MAX_UNITS = 256


class Observation(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    INCOMPLETE = "incomplete"
    NOT_CHECKED = "not_checked"


class SourceFamily(str, Enum):
    NOT_CHECKED = "not_checked"
    LOCAL = "local"
    PARENT = "parent"
    CONFLICT = "conflict"
    MISSING = "missing"


class Citation(str, Enum):
    NOT_CHECKED = "not_checked"
    LOCAL = "local"
    PARENT = "parent"
    BOTH = "both"
    ABSENT = "absent"


@dataclass(frozen=True)
class Relations:
    exact: Observation = Observation.NOT_CHECKED
    fragment: Observation = Observation.NOT_CHECKED
    edge_whitespace: Observation = Observation.NOT_CHECKED
    line_endings: Observation = Observation.NOT_CHECKED
    nfc: Observation = Observation.NOT_CHECKED
    nbsp: Observation = Observation.NOT_CHECKED
    json_escaping: Observation = Observation.NOT_CHECKED


@dataclass(frozen=True)
class Summary:
    source_family: SourceFamily = SourceFamily.NOT_CHECKED
    citation: Citation = Citation.NOT_CHECKED
    raw_equals_parsed: bool | None = None
    selected_raw: Relations = Relations()
    selected_parsed: Relations = Relations()
    other_raw_exact: Observation = Observation.NOT_CHECKED
    other_parsed_exact: Observation = Observation.NOT_CHECKED
    scan_complete: bool = False
    sources_scanned: int = 0
    units_scanned: int = 0


@dataclass
class Budget:
    nodes: int = 0
    characters: int = 0
    units: int = 0

    def preflight(self, value, depth=0):
        # Charge all visited nodes, including ineligible leaves. Limiting only
        # yielded units would allow an unbounded walk through nonnumeric input.
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            return False
        if isinstance(value, str):
            self.characters += len(value)
            return self.characters <= MAX_CHARACTERS
        if isinstance(value, Mapping):
            children = value.values()
        elif isinstance(value, (tuple, list)):
            children = value
        else:
            return True
        return all(self.preflight(child, depth + 1) for child in children)


def _relations(quote, units, complete):
    def result(predicate):
        if any(predicate(unit) for unit in units):
            return Observation.MATCH
        return Observation.NO_MATCH if complete else Observation.INCOMPLETE

    def difference(transform, unit):
        return quote != unit and transform(quote) == transform(unit)

    return Relations(
        exact=result(lambda u: quote == u),
        fragment=result(lambda u: quote != u and bool(quote) and quote in u),
        edge_whitespace=result(lambda u: difference(str.strip, u)),
        line_endings=result(lambda u: difference(lambda s: s.replace("\r\n", "\n").replace("\r", "\n"), u)),
        nfc=result(lambda u: difference(lambda s: unicodedata.normalize("NFC", s), u)),
        nbsp=result(lambda u: difference(lambda s: s.replace("\u00a0", " "), u)),
        json_escaping=result(lambda u: quote != u and any(
            quote == json.dumps(u, ensure_ascii=ascii_mode)[1:-1]
            for ascii_mode in (False, True))),
    )


def classify(payload, output, local, parents, error):
    """Caller supplies the very same authorized maps as numerical validation."""
    index, context_index = error.output_index, error.numeric_context_index
    if index is None or context_index is None:
        return Summary()  # text/items rejection: no quote probe
    raw_context = payload["outputs"][index]["numeric_context"][context_index]
    statement = output.outputs[index]
    context = statement.numeric_context[context_index]
    raw_quote, quote, identity = raw_context["quote"], context.quote, context.support_id
    if type(raw_quote) is not str or type(quote) is not str:
        return Summary()
    in_local, in_parent = identity in local, identity in parents
    family = (SourceFamily.CONFLICT if in_local and in_parent else
              SourceFamily.LOCAL if in_local else SourceFamily.PARENT if in_parent else SourceFamily.MISSING)
    cited_local, cited_parent = identity in statement.evidence_ids, identity in statement.parent_claim_ids
    citation = (Citation.BOTH if cited_local and cited_parent else Citation.LOCAL if cited_local else
                Citation.PARENT if cited_parent else Citation.ABSENT)
    # Exactly the validator's family precedence; collisions are observed, never
    # resolved. An uncited source is described in its own family if unambiguous.
    selected = ("local" if in_local and cited_local else "parent" if in_parent and cited_parent else
                "local" if in_local and not in_parent else "parent" if in_parent and not in_local else None)
    budget = Budget()
    selected_units, other_units = [], []
    selected_complete = selected is None
    complete, sources = True, 0

    def source_entries():
        if selected is not None:
            mapping = local if selected == "local" else parents
            yield selected, identity, mapping[identity]
        for name, mapping in (("local", local), ("parent", parents)):
            for key, source in mapping.items():
                if name != selected or key != identity:
                    yield name, key, source

    for name, key, source in source_entries():
        if sources >= MAX_SOURCES or not budget.preflight(source.value):
            complete = False
            break
        sources += 1
        units = []
        source_complete = True
        extractor = context_units if name == "local" else parent_context_units
        for unit in extractor(source.value):
            if budget.units >= MAX_UNITS:
                source_complete = complete = False
                break
            budget.units += 1
            units.append(unit)
        if name == selected and key == identity:
            selected_units = units
            selected_complete = source_complete
        elif key != identity:
            # Cross-family duplicate IDs are not "another source".
            other_units.extend(units)
        if not source_complete:
            break
    def other_exact(q):
        if q in other_units:
            return Observation.MATCH
        return Observation.NO_MATCH if complete else Observation.INCOMPLETE
    return Summary(
        source_family=family, citation=citation, raw_equals_parsed=raw_quote == quote,
        selected_raw=_relations(raw_quote, selected_units, selected_complete) if selected else Relations(),
        selected_parsed=_relations(quote, selected_units, selected_complete) if selected else Relations(),
        other_raw_exact=other_exact(raw_quote), other_parsed_exact=other_exact(quote),
        scan_complete=complete, sources_scanned=sources, units_scanned=budget.units,
    )


def observe(request, payload, output, evidence, parents, error, *, catalog_enabled):
    """Discard diagnostic exceptions, including messages, chains and tracebacks."""
    if (not isinstance(error, StatementSemanticsError)
            or error.rule is not SemanticRule.NUMERICAL_SUPPORT_REQUIRED):
        return
    summary = Summary()
    try:
        # evidence is the authoritative tuple from first_party_evidence. Bound
        # map construction too, not just the later source/unit traversal.
        if len(evidence) <= MAX_SOURCES:
            summary = classify(payload, output, {e.record.evidence_id: e for e in evidence}, parents, error)
    except Exception:
        pass
    # Explicit allowlist: no payload, quote, source, support ID or exception
    # reference enters the LogRecord (including extra/args/traceback).
    data = {
        "event": "virtual_cmo_numeric_rejected", "policy_version": POLICY_VERSION,
        "execution_id": request.execution_id, "stage": error.stage.value,
        "rule": error.rule.value,
        "reason": error.numeric_context_reason.value if error.numeric_context_reason else None,
        "location": error.numeric_location.value if error.numeric_location else None,
        "output_index": error.output_index, "numeric_context_index": error.numeric_context_index,
        "catalog_enabled": bool(catalog_enabled), "source_family": summary.source_family.value,
        "citation": summary.citation.value, "raw_equals_parsed": summary.raw_equals_parsed,
        "scan_complete": summary.scan_complete, "sources_scanned": summary.sources_scanned,
        "units_scanned": summary.units_scanned, "other_raw_exact": summary.other_raw_exact.value,
        "other_parsed_exact": summary.other_parsed_exact.value,
    }
    for prefix, relations in (("selected_raw", summary.selected_raw), ("selected_parsed", summary.selected_parsed)):
        for field in fields(Relations):
            data[prefix + "_" + field.name] = getattr(relations, field.name).value
    try:
        log.warning("%s", json.dumps(data, sort_keys=True))
    except Exception:
        pass  # Logging outage is also observational; never replaces rejection.
