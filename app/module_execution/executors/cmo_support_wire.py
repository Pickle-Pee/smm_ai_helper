"""Explicit keyed CMO outputs and support sets; canonical storage stays v1."""
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.module_execution.errors import ModuleExecutionContractError
from .cmo_provider_contract import cmo_provider_schema, QUALITATIVE_PATTERN
from .provider_schema import collapse_single_support_anyof
from .support_schema import check_schema_bounds
from .cmo_generation_policy import generation_field, validate_owner_catalog, validate_owner_quote_selection

WIRE_VERSION = "virtual_cmo.support_selection.v7"
MAX_SOURCE_CHOICES = 128
PARENT_MAP = "CMOAdditionalParentSupport"
EVIDENCE_MAP = "CMOAdditionalEvidenceSupport"
RISKS_DEFINITION = "CMORisksStatement"
RISK_TEXT_NOTES = (
    "Проверить риск расхождения между ожиданиями аудитории, тестируемым сообщением и подтверждёнными условиями продукта до масштабирования.",
    "Before scaling, check for mismatches between audience expectations, the tested message and confirmed product terms.",
)
RISK_ITEM_NOTES = (
    "Сопоставить ожидания аудитории с полным подтверждённым описанием продукта; не добавлять неподтверждённые свойства в сообщение.",
    "До проверки нового формата получить решение владельца; считать предлагаемые изменения неподтверждёнными до согласования.",
    "Проверить ресурсы и ограничения исполнения перед расширением; не считать масштабирование допустимым без соответствующих данных.",
    "Compare audience expectations with the complete confirmed owner terms; do not add unconfirmed product features to the message.",
    "Obtain the owner's decision before testing a new format; keep proposed changes unconfirmed until agreed.",
    "Check resources and delivery constraints before expanding; do not assume scaling is feasible without supporting data.",
)
ASSUMPTION_NOTES = (
    "Рабочие стратегические гипотезы требуют отдельной проверки перед использованием как подтверждённых выводов.",
    "Validate working strategic hypotheses before treating them as confirmed conclusions.",
)
STATEMENTS = ("MainGrowthConstraintStatement", "OtherStrategyStatement")
CANONICAL_FIELDS = {"output_name", "text", "items", "kind", "confidence", "evidence_ids", "parent_claim_ids", "numeric_context"}
SELECTION_FIELDS = {"primary_parent_key", "primary_evidence_key", "additional_parent_support", "additional_evidence_support"}
WIRE_FIELDS = (CANONICAL_FIELDS - {"output_name", "evidence_ids", "parent_claim_ids"}) | SELECTION_FIELDS


def _fail():
    raise ModuleExecutionContractError("Invalid CMO support selection wire") from None


def support_selection_catalog(evidence_ids, parent_ids):
    """Complete deterministic bijections; no truncation or content inference."""
    result = {}
    for name, prefix, identities in (("parents", "p", parent_ids), ("evidence", "e", evidence_ids)):
        values = tuple(identities)
        if any(type(value) is not str or not 1 <= len(value) <= 128 for value in values):
            _fail()
        values = sorted(set(values))
        if len(values) > MAX_SOURCE_CHOICES:
            _fail()
        result[name] = {f"{prefix}{index:03d}": value for index, value in enumerate(values)}
    if (not any(result.values()) or set(result["parents"].values()) & set(result["evidence"].values())):
        _fail()
    return result


def _boolean_map(aliases):
    return {"type": "object", "properties": {alias: {"type": "boolean"} for alias in aliases},
            "required": list(aliases), "additionalProperties": False}


def _closed_prose(field, maximum, notes, *, qualitative=False):
    allowed = {"type", "minLength", "maxLength", "title", "description"}
    if qualitative:
        allowed.add("pattern")
    if (type(field) is not dict or set(field) - allowed or field.get("type") != "string"
            or field.get("minLength") != 1 or field.get("maxLength") != maximum
            or (qualitative and field.get("pattern") != QUALITATIVE_PATTERN)):
        _fail()
    result = deepcopy(field)
    result.pop("pattern", None)
    result["enum"] = list(notes)
    return result


def _install_validation_policies(schema, names):
    """Bound risk/assumption prose, without granting product or market authority."""
    assumptions = schema["properties"]["assumptions"]
    if (set(assumptions) - {"type", "items", "maxItems", "minItems", "title", "description"}
            or assumptions.get("type") != "array" or assumptions.get("maxItems") != 12
            or assumptions.get("minItems", 0) != 0):
        _fail()
    assumptions["items"] = _closed_prose(assumptions["items"], 4000, ASSUMPTION_NOTES)
    if "risks" not in names:
        return
    risk = deepcopy(schema["$defs"][STATEMENTS[1]])
    props = risk["properties"]
    props["text"] = _closed_prose(props["text"], 4000, RISK_TEXT_NOTES, qualitative=True)
    items = props["items"]
    if (set(items) - {"type", "items", "maxItems", "minItems", "title", "description"}
            or items.get("type") != "array" or items.get("minItems") != 1 or items.get("maxItems") != 3):
        _fail()
    items["items"] = _closed_prose(items["items"], 300, RISK_ITEM_NOTES, qualitative=True)
    schema["$defs"][RISKS_DEFINITION] = risk


def _outputs(expected_outputs, definitions):
    names = tuple(expected_outputs)
    if not names or any(type(name) is not str for name in names) or len(names) != len(set(names)):
        _fail()
    main = definitions[STATEMENTS[0]]["properties"]["output_name"]
    other = definitions[STATEMENTS[1]]["properties"]["output_name"]
    if (main.get("const") != "main_growth_constraint" or type(other.get("enum")) is not list
            or "risks" not in other["enum"]):
        _fail()
    if not set(names) <= {main["const"], *other["enum"]}:
        _fail()
    return names


def support_selection_wire_schema(canonical_schema, expected_outputs, evidence_ids, parent_ids, catalog,
                                  owner_catalog=None):
    """Generate full closed boolean selections, not model-owned citation arrays."""
    try:
        aliases = support_selection_catalog(evidence_ids, parent_ids)
        owner_catalog = [] if owner_catalog is None else owner_catalog
        validate_owner_catalog(owner_catalog, set(aliases["evidence"].values()))
        schema = collapse_single_support_anyof(cmo_provider_schema(canonical_schema, catalog))
        definitions = schema["$defs"]
        if (any(name in definitions for name in (PARENT_MAP, EVIDENCE_MAP, RISKS_DEFINITION))
                or "wire_contract_version" in schema["properties"]):
            _fail()
        for name, definition_name in (("parents", "AllowedParentClaimId"), ("evidence", "AllowedEvidenceId")):
            if set(definitions.get(definition_name, {}).get("enum", [])) != set(aliases[name].values()):
                _fail()
        names = _outputs(expected_outputs, definitions)
        definitions[PARENT_MAP] = _boolean_map(aliases["parents"])
        definitions[EVIDENCE_MAP] = _boolean_map(aliases["evidence"])
        has_parents = bool(aliases["parents"])
        for name in STATEMENTS:
            node = definitions[name]
            props = node["properties"]
            if (set(node) - {"type", "properties", "required", "additionalProperties", "title"}
                    or node.get("type") != "object" or node.get("additionalProperties") is not False
                    or set(props) != CANONICAL_FIELDS or set(node.get("required", [])) != CANONICAL_FIELDS):
                _fail()
            if name == STATEMENTS[0]:
                if props["kind"].get("const") != "HYPOTHESIS":
                    _fail()
            elif set(props["kind"].get("enum", [])) != {"HYPOTHESIS", "RECOMMENDATION"}:
                _fail()
            for field in ("output_name", "evidence_ids", "parent_claim_ids"):
                props.pop(field)
            props["primary_parent_key"] = ({"type": "string", "enum": list(aliases["parents"])}
                                           if has_parents else {"type": "null"})
            props["primary_evidence_key"] = ({"type": "null"} if has_parents else
                                             {"type": "string", "enum": list(aliases["evidence"])})
            props["additional_parent_support"] = {"$ref": "#/$defs/" + PARENT_MAP}
            props["additional_evidence_support"] = {"$ref": "#/$defs/" + EVIDENCE_MAP}
            node["required"] = [field for field in node["required"]
                                if field not in {"output_name", "evidence_ids", "parent_claim_ids"}] + sorted(SELECTION_FIELDS)
        _install_validation_policies(schema, names)
        for definition in STATEMENTS:
            props = definitions[definition]["properties"]
            props["text"] = generation_field(props["text"], 4000, owner_catalog,
                                              original_pattern=QUALITATIVE_PATTERN)
            props["items"]["items"] = generation_field(props["items"]["items"], 300, owner_catalog,
                                                        original_pattern=QUALITATIVE_PATTERN)
        limitations = schema["properties"]["limitations"]
        if (set(limitations) - {"type", "items", "maxItems", "minItems", "title", "description"}
                or limitations.get("type") != "array" or limitations.get("maxItems") != 12
                or limitations.get("minItems", 0) != 0):
            _fail()
        limitations["items"] = generation_field(limitations["items"], 4000, [])
        schema["properties"]["outputs"] = {
            "type": "object", "properties": {name: {"$ref": "#/$defs/" + (
                STATEMENTS[0] if name == "main_growth_constraint" else
                RISKS_DEFINITION if name == "risks" else STATEMENTS[1])} for name in names},
            "required": list(names), "additionalProperties": False}
        schema["properties"]["wire_contract_version"] = {"type": "string", "enum": [WIRE_VERSION]}
        schema["required"].append("wire_contract_version")
        check_schema_bounds(schema)
        Draft202012Validator.check_schema(schema)
        return schema
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()


def decode_support_selection_wire(payload, canonical_schema, expected_outputs, evidence_ids, parent_ids, catalog,
                                  owner_catalog=None):
    """Decode explicit typed source sets, including explicitly selected quote pairs.

    Canonical arrays are absent and forbidden in wire input. Overlapping explicit
    choices denote one citation, not malformed arrays to repair. Content stays exact.
    The caller validates canonical bounds, Pydantic, semantics and gates afterwards.
    """
    try:
        evidence_ids, parent_ids = tuple(evidence_ids), tuple(parent_ids)
        aliases = support_selection_catalog(evidence_ids, parent_ids)
        names = tuple(expected_outputs)
        owner_catalog = [] if owner_catalog is None else owner_catalog
        wire_schema = support_selection_wire_schema(canonical_schema, names, evidence_ids, parent_ids, catalog,
                                                    owner_catalog)
        if type(payload) is not dict or not Draft202012Validator(wire_schema).is_valid(payload):
            _fail()
        if type(payload["outputs"]) is not dict or set(payload["outputs"]) != set(names):
            _fail()
        pairs = {(row["support_id"], row["exact_quote"]) for row in catalog}
        result = {key: deepcopy(value) for key, value in payload.items()
                  if key not in {"wire_contract_version", "outputs"}}
        outputs = []
        for name in names:
            statement = payload["outputs"][name]
            if type(statement) is not dict or set(statement) != WIRE_FIELDS:
                _fail()
            selected = {"parents": set(), "evidence": set()}
            for family, field in (("parents", "additional_parent_support"), ("evidence", "additional_evidence_support")):
                choices = statement[field]
                if type(choices) is not dict or set(choices) != set(aliases[family]):
                    _fail()
                for alias, enabled in choices.items():
                    if type(enabled) is not bool:
                        _fail()
                    if enabled:
                        selected[family].add(aliases[family][alias])
            if aliases["parents"]:
                if statement["primary_parent_key"] not in aliases["parents"] or statement["primary_evidence_key"] is not None:
                    _fail()
                selected["parents"].add(aliases["parents"][statement["primary_parent_key"]])
            else:
                if statement["primary_parent_key"] is not None or statement["primary_evidence_key"] not in aliases["evidence"]:
                    _fail()
                selected["evidence"].add(aliases["evidence"][statement["primary_evidence_key"]])
            for context in statement["numeric_context"]:
                if (context["support_id"], context["quote"]) not in pairs:
                    _fail()
                identity = context["support_id"]
                family = "parents" if identity in aliases["parents"].values() else "evidence"
                if identity not in aliases[family].values():
                    _fail()
                selected[family].add(identity)
            if name != "risks":
                validate_owner_quote_selection(statement, owner_catalog, selected["evidence"])
            canonical = {key: deepcopy(value) for key, value in statement.items() if key not in SELECTION_FIELDS}
            canonical.update(output_name=name, evidence_ids=sorted(selected["evidence"]),
                             parent_claim_ids=sorted(selected["parents"]))
            outputs.append(canonical)
        result["outputs"] = outputs
        return result
    except (SchemaError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        _fail()
