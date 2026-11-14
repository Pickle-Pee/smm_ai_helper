"""Typed additional EXPERIMENTS support sets; persisted payload stays v1."""
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from typing import get_args

from app.module_execution.errors import ModuleExecutionContractError
from .experiments_support_wire import (
    WIRE_VERSION as V2_VERSION, decode_strategic_parent_wire, QUALITATIVE_DESIGN_PATTERN,
    STATEMENT_NUMERIC_ASSERTION_DEFINITION, NUMERIC_ASSERTION_DEFINITION,
)
from .intelligence_schemas import ExperimentStatement
from .numeric_quantity import has_numeric_quantity
from .qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from .provider_schema import nodes
from .support_schema import MAX_SUPPORT_IDENTITIES, check_schema_bounds

WIRE_VERSION = "experiments.support_selection.v8"
MAX_REQUIRED_BOOLEAN_FLAGS = 2048
EVIDENCE_MAP = "ExperimentsAdditionalEvidenceSupport"
PARENT_MAP = "ExperimentsAdditionalParentSupport"
STATEMENT_FIELDS = {"output_name", "text", "kind", "confidence", "evidence_ids", "parent_claim_ids", "strategic_parent_id"}
EVIDENCE_BASIS_DEFINITION = "EvidenceBasisExperimentStatement"
GUARDRAILS_DEFINITION = "GuardrailsExperimentStatement"
CONTROL_DEFINITION = "ControlExperimentStatement"
TREATMENT_DEFINITION = "TreatmentExperimentStatement"
TEST_METHOD_DEFINITION = "TestMethodExperimentStatement"
OTHER_STATEMENT_DEFINITION = "OtherExperimentStatement"
EVIDENCE_BASIS_NOTES = (
    "Основанием для проверки служит принятая стратегическая гипотеза; она задаёт направление эксперимента, но не доказывает его результативность.",
    "The accepted strategic hypothesis guides the experiment; it does not establish the experiment's effectiveness.",
)
GUARDRAIL_NOTES = (
    "Публичное сообщение должно соответствовать подтверждённому описанию продукта; неподтверждённые свойства и результаты нельзя обещать.",
    "Public copy must match confirmed owner product descriptions; do not promise unconfirmed features or outcomes.",
)
CONTROL_NOTES = (
    "Подготовить новое нейтральное контрольное сообщение только по подтверждённому описанию продукта, без тестируемого акцента; согласовать текст с владельцем до запуска проверки.",
    "Prepare a new neutral control message using only confirmed owner product terms, without the tested emphasis; obtain the owner's approval before starting the test.",
)
TREATMENT_NOTES = (
    "Подготовить новое тестовое сообщение с акцентом из выбранной стратегической гипотезы, сохраняя подтверждённые факты о продукте; до запуска получить согласование владельца.",
    "Prepare a new test message emphasizing the selected strategic hypothesis while preserving confirmed product facts; obtain the owner's approval before the test.",
)
INTERVENTION_RECIPES = (
    "Подготовить новые контрольное и тестовое сообщения по выбранной гипотезе, согласовать их с владельцем, затем сравнить отклик сопоставимой аудитории. Контроль описывает подтверждённые факты; тест меняет только проверяемый акцент.",
    "Prepare new control and test messages for the selected hypothesis, obtain owner approval, then compare responses from comparable audiences. The control states confirmed facts; the test changes only the selected emphasis.",
    "Подготовить и согласовать с владельцем новые нейтральное и тестовое сообщения по выбранной гипотезе. Показать их целевой аудитории в качественных интервью; собрать понимание, причины предпочтения и сомнения без заявления о причинном эффекте.",
    "Prepare new neutral and test messages for the selected hypothesis and obtain owner approval. Show them to the target audience in qualitative interviews; collect understanding, reasons for preference and doubts without claiming a causal effect.",
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


def _policy_text(text, definitions, notes, *, maximum, numeric_definition, preserve_numeric=True):
    """Replace only a proved qualitative alternative; never expand numerical text."""
    qualitative = text
    if "anyOf" in text:
        if (set(text) != {"anyOf"} or len(text["anyOf"]) != 2
                or text["anyOf"][1] != {"$ref": "#/$defs/" + numeric_definition}):
            _fail()
        qualitative = text["anyOf"][0]
        numerical = definitions[numeric_definition]
        quotes = numerical.get("enum")
        if (set(numerical) != {"type", "minLength", "maxLength", "enum"}
                or numerical.get("type") != "string" or numerical.get("minLength") != 1
                or numerical.get("maxLength") != maximum or type(quotes) is not list or not quotes
                or any(type(quote) is not str or not 1 <= len(quote) <= maximum
                       or not has_numeric_quantity(quote) for quote in quotes)):
            _fail()
    if (set(qualitative) - {"type", "minLength", "maxLength", "title", "pattern"}
            or qualitative.get("type") != "string" or qualitative.get("minLength") != 1
            or qualitative.get("maxLength") != maximum
            or qualitative.get("pattern") != QUALITATIVE_DESIGN_PATTERN):
        _fail()
    policy = {key: value for key, value in qualitative.items() if key != "pattern"}
    policy["enum"] = list(notes)
    return ({"anyOf": [policy, deepcopy(text["anyOf"][1])]}
            if preserve_numeric and "anyOf" in text else policy)


def _specialize_policy_statements(definitions):
    """Close provenance/publication and operator plans, preserving other fields."""
    statement = definitions["ExperimentStatement"]
    props = statement["properties"]
    expected_names = list(get_args(ExperimentStatement.model_fields["output_name"].annotation))
    name = props["output_name"]
    if (set(name) - {"type", "enum", "title"} or name.get("type") != "string"
            or name.get("enum") != expected_names):
        _fail()
    policies = (("evidence_basis", EVIDENCE_BASIS_DEFINITION, EVIDENCE_BASIS_NOTES),
                ("guardrails", GUARDRAILS_DEFINITION, GUARDRAIL_NOTES),
                ("control", CONTROL_DEFINITION, CONTROL_NOTES),
                ("treatment", TREATMENT_DEFINITION, TREATMENT_NOTES),
                ("test_method", TEST_METHOD_DEFINITION, INTERVENTION_RECIPES))
    for output_name, definition, notes in policies:
        branch = deepcopy(statement)
        branch["properties"]["output_name"]["enum"] = [output_name]
        branch["properties"]["text"] = _policy_text(props["text"], definitions, notes, maximum=4000,
            numeric_definition=STATEMENT_NUMERIC_ASSERTION_DEFINITION, preserve_numeric=output_name != "evidence_basis")
        definitions[definition] = branch
    other = deepcopy(statement)
    other["properties"]["output_name"]["enum"] = [
        name for name in expected_names if name not in {row[0] for row in policies}]
    definitions[OTHER_STATEMENT_DEFINITION] = other
    definitions["ExperimentStatement"] = {"anyOf": [
        {"$ref": "#/$defs/" + definition} for _, definition, _ in policies
    ] + [{"$ref": "#/$defs/" + OTHER_STATEMENT_DEFINITION}]}
    design = definitions["ExperimentDesign"]["properties"]
    design["intervention"] = _policy_text(design["intervention"], definitions, INTERVENTION_RECIPES,
        maximum=300, numeric_definition=NUMERIC_ASSERTION_DEFINITION)


def support_selection_wire_schema(v2_schema, expected_output_count, evidence_ids, parent_ids):
    """Select citations and bounded policy notes; other V2 content survives."""
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
                                                        EVIDENCE_BASIS_DEFINITION, GUARDRAILS_DEFINITION,
                                                        CONTROL_DEFINITION, TREATMENT_DEFINITION, TEST_METHOD_DEFINITION,
                                                        OTHER_STATEMENT_DEFINITION))):
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
        _specialize_policy_statements(definitions)
        # Only free qualitative generation gets the small observed-count
        # filter. Complete source/numerical enums retain their exact text.
        for node in nodes(schema):
            if node.get("pattern") == QUALITATIVE_DESIGN_PATTERN:
                node["pattern"] = QUALITATIVE_GENERATION_PATTERN
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
        basis = [row for row in result["outputs"] if row["output_name"] == "evidence_basis"]
        if len(basis) > 1 or (expected_output_count == 16 and not basis):
            _fail()
        if basis:
            # The named provenance statement owns structured design evidence.
            # Move it without copying citations from any other output; partial
            # requests without it keep their original first-output contract.
            result["outputs"] = basis + [row for row in result["outputs"] if row["output_name"] != "evidence_basis"]
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
