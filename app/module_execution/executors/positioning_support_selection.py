"""Explicit keyed POSITIONING source sets; canonical storage remains v1."""
from copy import deepcopy
from hashlib import sha256
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.module_execution.errors import ModuleExecutionContractError
from .experiments_support_selection import support_selection_catalog, MAX_REQUIRED_BOOLEAN_FLAGS
from .product_support import PRODUCT_OUTPUTS, product_support_ids
from .support_schema import support_response_schema, check_schema_bounds
from .experiments_support_wire import assertion_text_schema
from .common import plain

WIRE_VERSION = "positioning.support_selection.v4"
FIELDS = {"output_name", "text", "kind", "confidence", "evidence_ids", "parent_claim_ids"}
SELECTION_FIELDS = {"primary_support_key", "evidence_support", "parent_support"}
MAPS = {"evidence": "PositioningEvidenceSelection", "parents": "PositioningParentSelection"}
SUPPORTED_ASSERTION = "AllowedPositioningSupportedAssertion"
QUALITATIVE_ASSERTION = "PositioningQualitativeAssertion"
TEXT_SELECTION = "PositioningTextSelection"
RTB_ASSERTION = "AllowedPositioningRTBAssertion"
RTB_TEXT = "PositioningRTBSourceText"


def _fail():
    raise ModuleExecutionContractError("Invalid POSITIONING support selection wire") from None


def _local_assertions(evidence):
    return tuple((e, e.value if isinstance(e.value, str)
        else json.dumps(plain(e.value), ensure_ascii=False)) for e in evidence)


def source_assertion_aliases(evidence, parent_assertions):
    """Use closed wire keys for source literals containing provider-forbidden quotes."""
    values = {value for _, value in _local_assertions(evidence)} | set(parent_assertions)
    quoted = {value for value in values if 1 <= len(value) <= 4000 and '"' in value}
    aliases = {"source_0_" + sha256(value.encode()).hexdigest(): value for value in quoted}
    if aliases.keys() & values or len(aliases) != len(quoted):
        _fail()
    return dict(sorted(aliases.items()))


def support_selection_wire_schema(canonical, output_type, names, evidence, parent_ids, *, parent_assertions=()):
    """Transform only the exact server-built contract, never unknown constraints."""
    try:
        names, evidence, parent_ids = tuple(names), tuple(evidence), tuple(parent_ids)
        evidence_ids = [e.record.evidence_id for e in evidence]
        choices = support_selection_catalog(evidence_ids, parent_ids)
        expected = support_response_schema(output_type, evidence_ids, parent_ids)
        if (json.dumps(canonical, sort_keys=True) != json.dumps(expected, sort_keys=True)
                or not names or len(names) != len(set(names)) or len(names) > 16
                or any(type(name) is not str for name in names)
                or len(names) * sum(map(len, choices.values())) > MAX_REQUIRED_BOOLEAN_FLAGS):
            _fail()
        definitions = {}
        local_assertions = _local_assertions(evidence)
        assertions = tuple(value for _, value in local_assertions) + tuple(parent_assertions)
        if any(type(value) is not str for value in assertions):
            _fail()
        alias_by_value = {value: alias for alias, value in source_assertion_aliases(
            evidence, parent_assertions).items()}
        supported = sorted({alias_by_value.get(value, value)
                            for value in assertions if 1 <= len(value) <= 4000})
        if supported:
            definitions[SUPPORTED_ASSERTION] = {"type": "string", "minLength": 1, "maxLength": 4000, "enum": supported}
        if "RTB" in names:
            rtb_values = sorted({alias_by_value.get(value, value) for e, value in local_assertions
                if e.input_key in {"product_truth", "existing_proof"} and 1 <= len(value) <= 4000})
            if not rtb_values:
                _fail()
            definitions[RTB_ASSERTION] = {"type": "string", "minLength": 1,
                "maxLength": 4000, "enum": rtb_values}
            definitions[RTB_TEXT] = {"type": "object", "properties": {
                "mode": {"type": "string", "enum": ["SOURCE"]},
                "value": {"$ref": "#/$defs/" + RTB_ASSERTION}},
                "required": ["mode", "value"], "additionalProperties": False}
        for family, definition in MAPS.items():
            definitions[definition] = {"type": "object",
                "properties": {key: {"type": "boolean"} for key in choices[family]},
                "required": list(choices[family]), "additionalProperties": False}
        schema = deepcopy(canonical)
        statements = [canonical["$defs"][v["$ref"].rsplit("/", 1)[-1]]
                      for v in canonical["properties"]["outputs"]["items"]["anyOf"]]
        selected_outputs = {}
        all_keys = [*choices["evidence"], *choices["parents"]]
        product_keys = [key for key, identity in choices["evidence"].items()
                        if identity in product_support_ids(evidence)]
        for index, name in enumerate(names):
            matches = [s for s in statements if name in s["properties"]["output_name"]["enum"]]
            if len(matches) != 1:
                _fail()
            statement = deepcopy(matches[0])
            if set(statement["properties"]) != FIELDS or set(statement["required"]) != FIELDS:
                _fail()
            # The exact reconstructed contract is checked above. Its support OR
            # is replaced by a mandatory explicit primary source, not dropped.
            statement.pop("anyOf", None)
            props = statement["properties"]
            text_schema = assertion_text_schema(props["text"], bool(supported),
                limit=4000, enum_definition=SUPPORTED_ASSERTION)
            qualitative = text_schema["anyOf"][0] if supported else text_schema
            if QUALITATIVE_ASSERTION in definitions and definitions[QUALITATIVE_ASSERTION] != qualitative:
                _fail()
            definitions[QUALITATIVE_ASSERTION] = qualitative
            # Explicit disjoint tags keep free prose and source literals from
            # competing as overlapping alternatives of one string. Decode only
            # the chosen value; the tag never grants source authority.
            text_choices = []
            for mode, value_definition in (("QUALITATIVE", QUALITATIVE_ASSERTION),
                                           ("SOURCE", SUPPORTED_ASSERTION)):
                if value_definition not in definitions:
                    continue
                definition = "Positioning" + mode.title() + "Text"
                definitions[definition] = {"type": "object", "properties": {
                    "mode": {"type": "string", "enum": [mode]},
                    "value": {"$ref": "#/$defs/" + value_definition}},
                    "required": ["mode", "value"], "additionalProperties": False}
                text_choices.append({"$ref": "#/$defs/" + definition})
            definitions[TEXT_SELECTION] = {"anyOf": text_choices}
            props["text"] = {"$ref": "#/$defs/" + (RTB_TEXT if name == "RTB" else TEXT_SELECTION)}
            for field in ("output_name", "evidence_ids", "parent_claim_ids"):
                props.pop(field)
            keys = product_keys if name in PRODUCT_OUTPUTS else all_keys
            if not keys:
                _fail()
            props["primary_support_key"] = {"type": "string", "enum": keys}
            props["evidence_support"] = {"$ref": "#/$defs/" + MAPS["evidence"]}
            props["parent_support"] = {"$ref": "#/$defs/" + MAPS["parents"]}
            statement["required"] = sorted(props)
            definition = "PositioningSelectedStatement" + str(index)
            definitions[definition] = statement
            selected_outputs[name] = {"$ref": "#/$defs/" + definition}
        schema["$defs"] = definitions
        schema["properties"]["outputs"] = {"type": "object", "properties": selected_outputs,
            "required": list(names), "additionalProperties": False}
        schema["properties"]["wire_contract_version"] = {"type": "string", "enum": [WIRE_VERSION]}
        schema["required"].append("wire_contract_version")
        check_schema_bounds(schema)
        Draft202012Validator.check_schema(schema)
        return schema
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()


def decode_support_selection_wire(payload, canonical, output_type, names, evidence, parent_ids, *, parent_assertions=()):
    """Only explicit typed choices become arrays; model arrays are forbidden."""
    try:
        names, evidence, parent_ids = tuple(names), tuple(evidence), tuple(parent_ids)
        choices = support_selection_catalog((e.record.evidence_id for e in evidence), parent_ids)
        schema = support_selection_wire_schema(canonical, output_type, names, evidence, parent_ids,
            parent_assertions=parent_assertions)
        if type(payload) is not dict or not Draft202012Validator(schema).is_valid(payload):
            _fail()
        result = deepcopy(payload)
        result.pop("wire_contract_version")
        aliases = source_assertion_aliases(evidence, parent_assertions)
        outputs = []
        for name in names:
            statement = result["outputs"][name]
            selected_text = statement["text"]
            value = selected_text["value"]
            statement["text"] = aliases.get(value, value) if selected_text["mode"] == "SOURCE" else value
            selected = {"evidence": set(), "parents": set()}
            primary = statement.pop("primary_support_key")
            for family, field in (("evidence", "evidence_support"), ("parents", "parent_support")):
                flags = statement.pop(field)
                if set(flags) != set(choices[family]) or any(type(value) is not bool for value in flags.values()):
                    _fail()
                selected[family].update(choices[family][key] for key, enabled in flags.items() if enabled)
                if primary in choices[family]:
                    selected[family].add(choices[family][primary])
            statement.update(output_name=name, evidence_ids=sorted(selected["evidence"]),
                parent_claim_ids=sorted(selected["parents"]))
            outputs.append(statement)
        result["outputs"] = outputs
        # Canonical JSON Schema, Pydantic, semantics and QG run independently next.
        return result
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()
