"""Request-owned provenance constraints shared by every statement wire type."""
from enum import Enum

from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError


# Each family fits below the provider's >250-value enum string restriction.
# Shared $defs avoid multiplying identity enums across statement OR branches.
MAX_SUPPORT_IDENTITIES = 250
MAX_SCHEMA_ENUM_VALUES = 1000
MAX_SCHEMA_STRING_CHARACTERS = 120000
SUPPORT_FIELDS = {"evidence_ids": "AllowedEvidenceId", "parent_claim_ids": "AllowedParentClaimId"}


class SupportRequirement(str, Enum):
    ANY = "any"
    PARENT_REQUIRED = "parent_required"


def support_response_schema(output_type, evidence_ids, parent_ids, *,
                            requirement: SupportRequirement = SupportRequirement.ANY):
    """Build/check one exact schema; never truncate or derive IDs from content."""
    allowed = {"evidence_ids": list(evidence_ids), "parent_claim_ids": list(parent_ids)}
    if type(requirement) is not SupportRequirement:
        raise ModuleExecutionContractError("Expected server support requirement")
    if requirement is SupportRequirement.PARENT_REQUIRED and not allowed["parent_claim_ids"]:
        raise ModuleExecutionContractError("Parent support requirement needs accepted parents")
    if not any(allowed.values()):
        raise ModuleExecutionContractError("Module generation requires available support")
    for identities in allowed.values():
        if any(
            type(value) is not str or not 1 <= len(value) <= 128 for value in identities
        ):
            raise ModuleExecutionContractError("Support identity allowlist exceeds contract bounds")
    allowed = {field: sorted(set(identities)) for field, identities in allowed.items()}
    if any(len(identities) > MAX_SUPPORT_IDENTITIES for identities in allowed.values()):
        raise ModuleExecutionContractError("Support identity allowlist exceeds contract bounds")
    schema = output_type.model_json_schema()

    def scope(node):
        if isinstance(node, list):
            for child in node:
                scope(child)
        elif isinstance(node, dict):
            properties = node.get("properties", {})
            if all(field in properties for field in SUPPORT_FIELDS):
                if requirement is SupportRequirement.PARENT_REQUIRED:
                    properties["parent_claim_ids"]["minItems"] = 1
                # OutputStatement owns this complete-object support OR. Remove
                # branches whose support floor refers to an unavailable family.
                if "anyOf" in node:
                    node["anyOf"] = [branch for branch in node["anyOf"] if not any(
                        not allowed[field] and branch.get("properties", {}).get(field, {}).get("minItems", 0)
                        for field in SUPPORT_FIELDS)]
                for field, definition in SUPPORT_FIELDS.items():
                    if allowed[field]:
                        properties[field]["items"] = {"$ref": f"#/$defs/{definition}"}
                    else:
                        properties[field]["maxItems"] = 0
            for child in node.values():
                scope(child)

    scope(schema)
    for field, definition in SUPPORT_FIELDS.items():
        if allowed[field]:
            schema.setdefault("$defs", {})[definition] = {
                "type": "string", "minLength": 1, "maxLength": 128, "enum": allowed[field],
            }
    enum_count = 0
    string_characters = 0

    def count(node):
        nonlocal enum_count, string_characters
        if isinstance(node, list):
            for child in node:
                count(child)
        elif isinstance(node, dict):
            enum_count += len(node.get("enum", []))
            string_characters += sum(len(key) for key in node.get("properties", {}))
            string_characters += sum(len(key) for key in node.get("$defs", {}))
            string_characters += sum(len(value) for value in node.get("enum", []) if isinstance(value, str))
            if isinstance(node.get("const"), str):
                string_characters += len(node["const"])
            for child in node.values():
                count(child)

    count(schema)
    if enum_count > MAX_SCHEMA_ENUM_VALUES or string_characters > MAX_SCHEMA_STRING_CHARACTERS:
        raise ModuleExecutionContractError("Request-scoped response schema exceeds provider bounds")
    Draft202012Validator.check_schema(schema)
    return schema
