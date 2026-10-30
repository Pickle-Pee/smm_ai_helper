"""Explicit strategic selection for EXPERIMENTS; persisted payload remains v1."""
from copy import deepcopy

from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError
from .provider_schema import collapse_redundant_support_anyof, collapse_single_support_anyof, nodes
from .support_schema import check_schema_bounds

WIRE_VERSION = "experiments.wire.v2"
SELECTED_PARENT = "strategic_parent_id"
STRATEGIC_DEFINITION = "AllowedStrategicParentId"


def strategic_parent_wire_schema(validation_schema, strategic_ids, constraints=()):
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
    if STRATEGIC_DEFINITION in definitions or "wire_contract_version" in schema["properties"]:
        raise ModuleExecutionContractError("Unexpected strategic parent wire contract")
    definitions[STRATEGIC_DEFINITION] = {"type": "string", "minLength": 1, "maxLength": 128, "enum": allowed}
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
        properties[SELECTED_PARENT] = {"$ref": "#/$defs/" + STRATEGIC_DEFINITION}
        node["required"].append(SELECTED_PARENT)
        # The explicit scalar supplies the original mandatory parent floor.
        properties["parent_claim_ids"]["minItems"] = 0
        properties["parent_claim_ids"]["maxItems"] = 31
        statements += 1
    design = definitions.get("ExperimentDesign", {}).get("properties", {})
    if not statements or "related_strategic_claim_ids" not in design:
        raise ModuleExecutionContractError("Missing strategic parent wire contract")
    design["related_strategic_claim_ids"]["items"] = {"$ref": "#/$defs/" + STRATEGIC_DEFINITION}
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
