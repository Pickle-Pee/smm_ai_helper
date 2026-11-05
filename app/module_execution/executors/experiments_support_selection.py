"""Typed additional EXPERIMENTS support sets; persisted payload stays v1."""
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from typing import get_args

from app.module_execution.errors import ModuleExecutionContractError
from .experiments_support_wire import (
    WIRE_VERSION as V2_VERSION, decode_strategic_parent_wire, QUALITATIVE_DESIGN_PATTERN,
    STATEMENT_NUMERIC_ASSERTION_DEFINITION,
)
from .intelligence_schemas import ExperimentStatement
from .provider_schema import nodes
from .support_schema import MAX_SUPPORT_IDENTITIES, check_schema_bounds

WIRE_VERSION = "experiments.support_selection.v4"
MAX_REQUIRED_BOOLEAN_FLAGS = 2048
EVIDENCE_MAP = "ExperimentsAdditionalEvidenceSupport"
PARENT_MAP = "ExperimentsAdditionalParentSupport"
STATEMENT_FIELDS = {"output_name", "text", "kind", "confidence", "evidence_ids", "parent_claim_ids", "strategic_parent_id"}
EVIDENCE_BASIS_DEFINITION = "EvidenceBasisExperimentStatement"
OTHER_STATEMENT_DEFINITION = "OtherExperimentStatement"
EVIDENCE_BASIS_NOTES = (
    "Основанием для проверки служит принятая стратегическая гипотеза; она задаёт направление эксперимента, но не доказывает его результативность.",
    "The accepted strategic hypothesis guides the experiment; it does not establish the experiment's effectiveness.",
)


def _fail():
    raise ModuleExecutionContractError("Invalid EXPERIMENTS support selection wire") from None


def support_selection_catalog(evidence_ids, parent_ids):
    """Complete source bijections; retain the canonical 250/family scope cap."""
    result = {}
    for family, prefix, identities in (("evidence", "e", evidence_ids), ("parents", "p", parent_ids)):
        values = tuple(identities)
        if any(type(value) is not str or not 1 <= len(value) <= 128 for value in values):
            _fail()
        values = sorted(set(values))
        if len(values) > MAX_SUPPORT_IDENTITIES:
            _fail()
        result[family] = {f"{prefix}{index:03d}": value for index, value in enumerate(values)}
    if not any(result.values()) or set(result["evidence"].values()) & set(result["parents"].values()):
        _fail()
    return result


def _boolean_map(aliases):
    return {"type": "object", "properties": {alias: {"type": "boolean"} for alias in aliases},
            "required": list(aliases), "additionalProperties": False}


def _specialize_evidence_basis(definitions):
    """Constrain one provenance note, preserving all other statement contracts."""
    statement = definitions["ExperimentStatement"]
    props = statement["properties"]
    expected_names = list(get_args(ExperimentStatement.model_fields["output_name"].annotation))
    name = props["output_name"]
    if (set(name) - {"type", "enum", "title"} or name.get("type") != "string"
            or name.get("enum") != expected_names or "evidence_basis" not in expected_names):
        _fail()
    text = props["text"]
    qualitative = text
    if "anyOf" in text:
        if (set(text) != {"anyOf"} or len(text["anyOf"]) != 2
                or text["anyOf"][1] != {"$ref": "#/$defs/" + STATEMENT_NUMERIC_ASSERTION_DEFINITION}):
            _fail()
        qualitative = text["anyOf"][0]
    if (set(qualitative) - {"type", "minLength", "maxLength", "title", "pattern"}
            or qualitative.get("type") != "string" or qualitative.get("minLength") != 1
            or qualitative.get("maxLength") != 4000
            or qualitative.get("pattern") != QUALITATIVE_DESIGN_PATTERN):
        _fail()
    basis, other = deepcopy(statement), deepcopy(statement)
    basis["properties"]["output_name"]["enum"] = ["evidence_basis"]
    basis["properties"]["text"] = {key: value for key, value in qualitative.items() if key != "pattern"}
    basis["properties"]["text"]["enum"] = list(EVIDENCE_BASIS_NOTES)
    other["properties"]["output_name"]["enum"] = [name for name in expected_names if name != "evidence_basis"]
    definitions[EVIDENCE_BASIS_DEFINITION] = basis
    definitions[OTHER_STATEMENT_DEFINITION] = other
    definitions["ExperimentStatement"] = {"anyOf": [
        {"$ref": "#/$defs/" + EVIDENCE_BASIS_DEFINITION},
        {"$ref": "#/$defs/" + OTHER_STATEMENT_DEFINITION},
    ]}


def support_selection_wire_schema(v2_schema, expected_output_count, evidence_ids, parent_ids):
    """Select citations and a closed evidence-basis note; other V2 content survives."""
    try:
        choices = support_selection_catalog(evidence_ids, parent_ids)
        if (type(expected_output_count) is not int or not 1 <= expected_output_count <= 16
                or expected_output_count * sum(map(len, choices.values())) > MAX_REQUIRED_BOOLEAN_FLAGS):
            _fail()
        Draft202012Validator.check_schema(v2_schema)
        schema = deepcopy(v2_schema)
        definitions = schema["$defs"]
        if (schema["properties"]["wire_contract_version"] != {"type": "string", "enum": [V2_VERSION]}
                or schema["properties"]["outputs"].get("type") != "array"
                or schema["properties"]["outputs"].get("items") != {"$ref": "#/$defs/ExperimentStatement"}
                or any(name in definitions for name in (EVIDENCE_MAP, PARENT_MAP,
                                                        EVIDENCE_BASIS_DEFINITION, OTHER_STATEMENT_DEFINITION))):
            _fail()
        for family, definition in (("evidence", "AllowedEvidenceId"), ("parents", "AllowedParentClaimId")):
            scoped = definitions.get(definition)
            if choices[family]:
                if (type(scoped) is not dict or set(scoped) != {"type", "minLength", "maxLength", "enum"}
                        or scoped.get("type") != "string" or scoped.get("minLength") != 1
                        or scoped.get("maxLength") != 128
                        or set(scoped.get("enum", [])) != set(choices[family].values())):
                    _fail()
            elif scoped is not None:
                _fail()
        eligible = definitions["AllowedStrategicParentId"]["enum"]
        if not eligible or not set(eligible) <= set(choices["parents"].values()):
            _fail()
        definitions[EVIDENCE_MAP] = _boolean_map(choices["evidence"])
        definitions[PARENT_MAP] = _boolean_map(choices["parents"])
        count = 0
        for node in list(nodes(schema)):
            props = node.get("properties", {})
            if not {"output_name", "strategic_parent_id"} <= props.keys():
                continue
            if (set(node) - {"type", "properties", "required", "additionalProperties", "title"}
                    or node is not definitions.get("ExperimentStatement")
                    or set(props) != STATEMENT_FIELDS or set(node.get("required", [])) != STATEMENT_FIELDS
                    or node.get("type") != "object" or node.get("additionalProperties") is not False
                    or "anyOf" in node or props["strategic_parent_id"] != {"$ref": "#/$defs/AllowedStrategicParentId"}):
                _fail()
            for field, family, definition, maximum in (("evidence_ids", "evidence", EVIDENCE_MAP, 32),
                                                       ("parent_claim_ids", "parents", PARENT_MAP, 31)):
                value = props[field]
                identity_definition = "AllowedEvidenceId" if family == "evidence" else "AllowedParentClaimId"
                if (set(value) - {"type", "items", "minItems", "maxItems", "title"}
                        or value.get("type") != "array" or value.get("minItems", 0) != 0
                        or value.get("maxItems") != (maximum if choices[family] else 0)
                        or (choices[family] and value.get("items") != {"$ref": "#/$defs/" + identity_definition})):
                    _fail()
                props.pop(field)
                replacement = "additional_evidence_support" if family == "evidence" else "additional_parent_support"
                props[replacement] = {"$ref": "#/$defs/" + definition}
                node["required"] = [replacement if name == field else name for name in node["required"]]
            count += 1
        if count != 1:
            _fail()
        _specialize_evidence_basis(definitions)
        schema["properties"]["wire_contract_version"]["enum"] = [WIRE_VERSION]
        # References cannot point into removed fields or outside this schema.
        for node in nodes(schema):
            if "$ref" in node:
                ref = node["$ref"]
                if (type(ref) is not str or not ref.startswith("#/$defs/")
                        or "/" in ref[len("#/$defs/"):] or "~" in ref[len("#/$defs/"):]
                        or ref[len("#/$defs/"):] not in definitions):
                    _fail()
        check_schema_bounds(schema)
        Draft202012Validator.check_schema(schema)
        return schema
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()


def decode_support_selection_wire(payload, v2_schema, expected_output_count, evidence_ids, parent_ids):
    """Map explicit sets only; legacy malformed arrays are absent/forbidden.

    Primary and additional-true overlap denotes one citation. No text or numeric
    assertion selects a source implicitly. Original canonical bounds apply next.
    """
    try:
        evidence_ids, parent_ids = tuple(evidence_ids), tuple(parent_ids)
        choices = support_selection_catalog(evidence_ids, parent_ids)
        schema = support_selection_wire_schema(v2_schema, expected_output_count, evidence_ids, parent_ids)
        if type(payload) is not dict or not Draft202012Validator(schema).is_valid(payload):
            _fail()
        result = deepcopy(payload)
        result["wire_contract_version"] = V2_VERSION
        for statement in result["outputs"]:
            for family, field, output in (("evidence", "additional_evidence_support", "evidence_ids"),
                                          ("parents", "additional_parent_support", "parent_claim_ids")):
                selected = statement.pop(field)
                if type(selected) is not dict or set(selected) != set(choices[family]):
                    _fail()
                if any(type(value) is not bool for value in selected.values()):
                    _fail()
                statement[output] = sorted(choices[family][alias] for alias, value in selected.items() if value)
        # Reuse the original scalar-selection decoder. These internal arrays are
        # generated from sets, never repaired model arrays; canonical 32 remains.
        return decode_strategic_parent_wire(result, v2_schema["$defs"]["AllowedStrategicParentId"]["enum"])
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()
