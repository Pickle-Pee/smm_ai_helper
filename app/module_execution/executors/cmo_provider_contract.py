"""Bounded provider constraints; canonical CMO validation remains authoritative."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .numeric_grounding import MAX_NUMERIC_QUOTE_CATALOG_BYTES, MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
from .provider_schema import SchemaProjectionError, collapse_redundant_support_anyof, nodes
from .support_schema import check_schema_bounds

QUALITATIVE_PATTERN = "^[^0-9]*$"
_STRING_KEYS = {"type", "minLength", "maxLength", "title", "description", "pattern"}
_OBJECT_KEYS = {"type", "properties", "required", "additionalProperties", "title"}


def _fail():
    raise SchemaProjectionError("cmo_provider_contract_unproved") from None


def _qualitative_text(field, maximum):
    if (type(field) is not dict or not set(field) <= _STRING_KEYS
            or field.get("type") != "string" or field.get("minLength") != 1
            or field.get("maxLength") != maximum
            or field.get("pattern", QUALITATIVE_PATTERN) != QUALITATIVE_PATTERN):
        _fail()
    field["pattern"] = QUALITATIVE_PATTERN


def qualitative_cmo_schema(schema):
    """Independent, idempotent ASCII-generation constraint, not a Unicode proof."""
    try:
        if type(schema) is not dict:
            _fail()
        json.dumps(schema, allow_nan=False)
        Draft202012Validator.check_schema(schema)
        result = deepcopy(schema)
        if not {"MainGrowthConstraintStatement", "OtherStrategyStatement"} <= result.get("$defs", {}).keys():
            _fail()
        count = 0
        for node in nodes(result):
            properties = node.get("properties", {})
            if not {"output_name", "evidence_ids", "parent_claim_ids", "numeric_context", "items"} <= properties.keys():
                continue
            _qualitative_text(properties.get("text"), 4000)
            items = properties["items"]
            context = properties["numeric_context"]
            if (items.get("type") != "array" or items.get("minItems") != 1
                    or items.get("maxItems") not in (1, 3)
                    or context.get("type") != "array"
                    or context.get("items") != {"$ref": "#/$defs/NumericContext"}
                    or context.get("maxItems") != 3 or context.get("minItems", 0) != 0):
                _fail()
            _qualitative_text(items.get("items"), 300)
            count += 1
        if not count:
            _fail()
        return result
    except (SchemaError, TypeError, ValueError, KeyError, AttributeError, RecursionError):
        _fail()


def cmo_provider_schema(validation_schema, catalog):
    """Restrict to complete same-source catalog pairs, without adding citations.

    The caller obtains the catalog exclusively from numeric_quote_catalog with
    request-authorized evidence/parents. Its existing caps intentionally make
    this a bounded provider subset, not structural-schema equivalence.
    """
    try:
        result = qualitative_cmo_schema(collapse_redundant_support_anyof(validation_schema))
        definitions = result["$defs"]
        numeric = definitions["NumericContext"]
        if (not set(numeric) <= _OBJECT_KEYS or numeric.get("type") != "object"
                or numeric.get("additionalProperties") is not False
                or set(numeric.get("properties", {})) != {"support_id", "quote"}
                or set(numeric.get("required", [])) != {"support_id", "quote"}):
            _fail()
        quote = numeric["properties"]["quote"]
        if (not set(quote) <= _STRING_KEYS - {"pattern"} or quote.get("type") != "string"
                or quote.get("minLength") != 1 or quote.get("maxLength") != 1000):
            _fail()
        support = numeric["properties"]["support_id"]
        if set(support) != {"anyOf"} or not 1 <= len(support["anyOf"]) <= 2:
            _fail()
        identities = set()
        for branch in support["anyOf"]:
            if (set(branch) != {"$ref"} or branch["$ref"] not in
                    ("#/$defs/AllowedEvidenceId", "#/$defs/AllowedParentClaimId")):
                _fail()
            definition = definitions[branch["$ref"].split("/")[-1]]
            if (set(definition) != {"type", "minLength", "maxLength", "enum"}
                    or definition["type"] != "string" or definition["minLength"] != 1
                    or definition["maxLength"] != 128
                    or type(definition["enum"]) is not list or not definition["enum"]
                    or any(type(value) is not str or not 1 <= len(value) <= 128 for value in definition["enum"])
                    or identities.intersection(definition["enum"])):
                _fail()
            identities.update(definition["enum"])
        if (type(catalog) is not list or len(catalog) > MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
                or len(json.dumps(catalog, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_NUMERIC_QUOTE_CATALOG_BYTES):
            _fail()
        grouped = {}
        for entry in catalog:
            if type(entry) is not dict or set(entry) != {"support_id", "exact_quote"}:
                _fail()
            identity, text = entry["support_id"], entry["exact_quote"]
            if (type(identity) is not str or identity not in identities or type(text) is not str
                    or not 1 <= len(text) <= 1000):
                _fail()
            grouped.setdefault(identity, set()).add(text)
        if grouped:
            alternatives = []
            for identity, quotes in sorted(grouped.items()):
                branch = deepcopy(numeric)
                branch.pop("title", None)
                branch["properties"]["support_id"] = {
                    "type": "string", "minLength": 1, "maxLength": 128, "enum": [identity]}
                branch["properties"]["quote"]["enum"] = sorted(quotes)
                alternatives.append(branch)
            definitions["NumericContext"] = {"anyOf": alternatives}
            if "title" in numeric:
                definitions["NumericContext"]["title"] = numeric["title"]
        else:
            for node in nodes(result):
                context = node.get("properties", {}).get("numeric_context")
                if context is not None:
                    context["maxItems"] = 0
        check_schema_bounds(result)
        Draft202012Validator.check_schema(result)
        return result
    except (SchemaError, TypeError, ValueError, KeyError, AttributeError, RecursionError, UnicodeError):
        _fail()
