"""POSITIONING product support policy and explicit versioned wire mapping."""
from copy import deepcopy

from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError


PRODUCT_OUTPUTS = frozenset({"RTB", "value_proposition", "positioning_statement", "offer"})
PRODUCT_CATEGORIES = frozenset({"product_truth", "existing_proof"})
WIRE_VERSION = "positioning.wire.v2"


def product_support_ids(evidence):
    return sorted({item.record.evidence_id for item in evidence if item.input_key in PRODUCT_CATEGORIES})


def product_wire_schema(validation_schema, evidence):
    """Disjoint names force selection from the exact request's product support."""
    from .support_schema import check_schema_bounds

    ids = product_support_ids(evidence)
    if not ids:
        raise ModuleExecutionContractError("Product support wire requires local truth or proof")
    schema = deepcopy(validation_schema)
    definitions = schema["$defs"]
    product = None
    # Narrow every complete-object branch, not just its outer name property.
    def narrow(node):
        if isinstance(node, list):
            for child in node:
                narrow(child)
        elif isinstance(node, dict):
            name = node.get("properties", {}).get("output_name", {})
            if "enum" in name:
                name["enum"] = [value for value in name["enum"] if value not in PRODUCT_OUTPUTS]
            for child in node.values():
                narrow(child)

    for definition in list(definitions.values()):
        properties = definition.get("properties", {})
        names = properties.get("output_name", {}).get("enum", [])
        if PRODUCT_OUTPUTS.intersection(names):
            if not PRODUCT_OUTPUTS <= set(names):
                raise ModuleExecutionContractError("Unexpected POSITIONING product statement contract")
            if product is None:
                product = deepcopy(definition)
            narrow(definition)
    if product is None:
        raise ModuleExecutionContractError("Missing POSITIONING product statement contract")
    # The scalar selected by the model supplies the support floor. Additional
    # evidence retains its original authority, with one slot reserved for it.
    product.pop("anyOf", None)
    product["title"] = "PositioningProductStatementV2"
    product["properties"]["output_name"]["enum"] = sorted(PRODUCT_OUTPUTS)
    product["properties"]["evidence_ids"]["maxItems"] = 31
    product["properties"]["product_support_id"] = {"$ref": "#/$defs/AllowedProductSupportId"}
    product["required"].append("product_support_id")
    definitions["PositioningProductStatementV2"] = product
    definitions["AllowedProductSupportId"] = {"type": "string", "enum": ids}
    schema["properties"]["outputs"]["items"]["anyOf"].append(
        {"$ref": "#/$defs/PositioningProductStatementV2"})
    schema["properties"]["wire_contract_version"] = {"type": "string", "enum": [WIRE_VERSION]}
    schema["required"].append("wire_contract_version")
    check_schema_bounds(schema)
    Draft202012Validator.check_schema(schema)
    return schema


def decode_product_wire(payload, evidence):
    """Map an explicit model selection; never infer a citation or invent an ID."""
    if payload.get("wire_contract_version") != WIRE_VERSION:
        raise ValueError("Unexpected product wire version")
    allowed = set(product_support_ids(evidence))
    result = deepcopy(payload)
    result.pop("wire_contract_version")
    for statement in result["outputs"]:
        if statement["output_name"] not in PRODUCT_OUTPUTS:
            if "product_support_id" in statement:
                raise ValueError("Unexpected product support selection")
            continue
        selected = statement.pop("product_support_id", None)
        if selected not in allowed or selected in statement["evidence_ids"]:
            raise ValueError("Invalid explicit product support selection")
        statement["evidence_ids"] = [selected, *statement["evidence_ids"]]
    return result
