"""Explicit strategic selection for EXPERIMENTS; persisted payload remains v1."""
from copy import deepcopy
import re

from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError
from .provider_schema import collapse_redundant_support_anyof, collapse_single_support_anyof, nodes
from .support_schema import check_schema_bounds

WIRE_VERSION = "experiments.wire.v2"
SELECTED_PARENT = "strategic_parent_id"
STRATEGIC_DEFINITION = "AllowedStrategicParentId"
NUMERIC_ASSERTION_DEFINITION = "AllowedExperimentNumericAssertion"
STATEMENT_NUMERIC_ASSERTION_DEFINITION = "AllowedExperimentStatementNumericAssertion"


QUALITATIVE_DESIGN_PATTERN = "^[^0-9]*$"


def assertion_text_schema(original, numeric_assertions_available, *, limit, enum_definition):
    """Generate qualitative text or a complete, bounded supplied assertion.

    The portable provider pattern excludes ASCII digits. The unchanged canonical
    numerical guard remains authoritative for all Unicode decimal digits and for
    actual cited-source provenance.
    """
    if (original.get("type") != "string" or original.get("minLength") != 1
            or original.get("maxLength") != limit
            or any(key in original for key in ("anyOf", "allOf", "oneOf", "pattern", "enum", "$ref"))):
        raise ModuleExecutionContractError("Unexpected experiment assertion text contract")
    qualitative = deepcopy(original)
    qualitative["pattern"] = QUALITATIVE_DESIGN_PATTERN
    if not numeric_assertions_available:
        return qualitative
    return {"anyOf": [qualitative, {"$ref": "#/$defs/" + enum_definition}]}


def strategic_parent_wire_schema(validation_schema, strategic_ids, constraints=(), strategic_assertions=(),
                                 *, statement_assertions=()):
    """Reserve one canonical parent slot for an explicit accepted hypothesis.

    Additional parents retain the original complete allowlist, including accepted
    observations. No hypothesis is inferred from text or substituted by code.
    """
    allowed = sorted(set(strategic_ids))
    parents = validation_schema.get("$defs", {}).get("AllowedParentClaimId", {}).get("enum", [])
    if (not allowed or any(type(value) is not str or not 1 <= len(value) <= 128 for value in allowed)
            or not set(allowed) <= set(parents)):
        raise ModuleExecutionContractError("Invalid strategic parent wire scope")
    schema = collapse_redundant_support_anyof(validation_schema)
    schema = collapse_single_support_anyof(schema)
    definitions = schema["$defs"]
    if (any(name in definitions for name in (STRATEGIC_DEFINITION, NUMERIC_ASSERTION_DEFINITION,
                                            STATEMENT_NUMERIC_ASSERTION_DEFINITION))
            or "wire_contract_version" in schema["properties"]):
        raise ModuleExecutionContractError("Unexpected strategic parent wire contract")
    definitions[STRATEGIC_DEFINITION] = {"type": "string", "minLength": 1, "maxLength": 128, "enum": allowed}
    statement_assertions = tuple(statement_assertions)
    if any(type(value) is not str for value in statement_assertions):
        raise ModuleExecutionContractError("Invalid experiment statement assertion wire scope")
    statement_numeric_assertions = sorted({text for text in statement_assertions
                                          if 1 <= len(text) <= 4000 and re.search(r"\d", text)})
    if statement_numeric_assertions:
        definitions[STATEMENT_NUMERIC_ASSERTION_DEFINITION] = {
            "type": "string", "minLength": 1, "maxLength": 4000, "enum": statement_numeric_assertions}
    statements = 0
    for node in nodes(schema):
        properties = node.get("properties", {})
        if not {"output_name", "evidence_ids", "parent_claim_ids"} <= properties.keys():
            continue
        if ("anyOf" in node or SELECTED_PARENT in properties
                or properties["parent_claim_ids"].get("minItems", 0) < 1):
            raise ModuleExecutionContractError("Unexpected strategic parent statement contract")
        # Exactly the kinds already accepted by the canonical local guard.
        if set(properties.get("kind", {}).get("enum", ())) != {"OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"}:
            raise ModuleExecutionContractError("Unexpected experiment statement kind contract")
        properties["kind"]["enum"] = ["HYPOTHESIS", "RECOMMENDATION"]
        properties["text"] = assertion_text_schema(properties["text"], bool(statement_numeric_assertions),
            limit=4000, enum_definition=STATEMENT_NUMERIC_ASSERTION_DEFINITION)
        properties[SELECTED_PARENT] = {"$ref": "#/$defs/" + STRATEGIC_DEFINITION}
        node["required"].append(SELECTED_PARENT)
        # The explicit scalar supplies the original mandatory parent floor.
        properties["parent_claim_ids"]["minItems"] = 0
        properties["parent_claim_ids"]["maxItems"] = 31
        statements += 1
    design = definitions.get("ExperimentDesign", {}).get("properties", {})
    if not statements or "related_strategic_claim_ids" not in design:
        raise ModuleExecutionContractError("Missing strategic parent wire contract")
    # Generation targets one primary falsifiable hypothesis per design. The
    # canonical payload still permits multiple refs and rejects duplicates.
    design["related_strategic_claim_ids"]["minItems"] = 1
    design["related_strategic_claim_ids"]["maxItems"] = 1
    design["related_strategic_claim_ids"]["items"] = {"$ref": "#/$defs/" + STRATEGIC_DEFINITION}
    strategic_assertions = tuple(strategic_assertions)
    if any(type(value) is not str for value in strategic_assertions):
        raise ModuleExecutionContractError("Invalid experiment assertion wire scope")
    numeric_assertions = sorted({text for text in strategic_assertions
                                 if 1 <= len(text) <= 300 and re.search(r"\d", text)})
    if numeric_assertions:
        definitions[NUMERIC_ASSERTION_DEFINITION] = {
            "type": "string", "minLength": 1, "maxLength": 300, "enum": numeric_assertions}
    for name, definition in tuple(design.items()):
        if name in ("related_strategic_claim_ids", "time_resource_constraints"):
            continue
        if name == "minimum_required_inputs":
            definition["items"] = assertion_text_schema(definition["items"], bool(numeric_assertions),
                limit=300, enum_definition=NUMERIC_ASSERTION_DEFINITION)
        else:
            design[name] = assertion_text_schema(definition, bool(numeric_assertions),
                limit=300, enum_definition=NUMERIC_ASSERTION_DEFINITION)
    constraints = tuple(constraints)
    if any(type(value) is not str or not 1 <= len(value) <= 300 for value in constraints):
        raise ModuleExecutionContractError("Invalid experiment constraint wire scope")
    allowed_constraints = sorted(set(constraints))
    if len(allowed_constraints) > 8:
        raise ModuleExecutionContractError("Experiment constraint wire scope exceeds bounds")
    constraint_schema = design["time_resource_constraints"]
    constraint_schema["minItems"] = len(allowed_constraints)
    constraint_schema["maxItems"] = len(allowed_constraints)
    if allowed_constraints:
        constraint_schema["items"] = {"type": "string", "enum": allowed_constraints}
    schema["properties"]["wire_contract_version"] = {"type": "string", "enum": [WIRE_VERSION]}
    schema["required"].append("wire_contract_version")
    check_schema_bounds(schema)
    Draft202012Validator.check_schema(schema)
    return schema


def decode_strategic_parent_wire(payload, strategic_ids):
    """Decode model selections, preserving every additional citation verbatim.

    A selected ID already present exactly once is an explicit alias for that
    citation, not an extra canonical occurrence. Duplicates inside either array
    are rejected, never deduplicated. The caller validates full v1 afterwards.
    """
    if payload.get("wire_contract_version") != WIRE_VERSION:
        raise ValueError("Unexpected strategic parent wire version")
    allowed = set(strategic_ids)
    result = deepcopy(payload)
    result.pop("wire_contract_version")
    for statement in result["outputs"]:
        selected = statement.pop(SELECTED_PARENT, None)
        if type(selected) is not str or selected not in allowed:
            raise ValueError("Invalid explicit strategic parent selection")
        for name in ("evidence_ids", "parent_claim_ids"):
            refs = statement[name]
            if type(refs) is not list or any(type(ref) is not str for ref in refs) or len(refs) != len(set(refs)):
                raise ValueError("Duplicate or invalid support references")
        parents = statement["parent_claim_ids"]
        if selected not in parents:
            statement["parent_claim_ids"] = [selected, *parents]
    return result
