"""Equivalent provider schema projection; full server contracts stay authoritative."""
from copy import deepcopy
import hashlib
import json

from app.module_execution.errors import ModuleExecutionContractError


class SchemaProjectionError(ModuleExecutionContractError):
    """Closed proof refusal; never contains schema or provider data."""


MAPS = ("properties", "$defs", "definitions", "patternProperties", "dependentSchemas")
LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
SINGLES = ("items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames")


def children(node, *, definitions=True):
    for key in MAPS:
        if not definitions and key in ("$defs", "definitions"):
            continue
        for value in node.get(key, {}).values():
            if isinstance(value, dict):
                yield value
    for key in LISTS:
        for value in node.get(key, []):
            if isinstance(value, dict):
                yield value
    for key in SINGLES:
        value = node.get(key)
        if isinstance(value, dict):
            yield value


def nodes(schema):
    yield schema
    for child in children(schema):
        yield from nodes(child)


def collapse_single_support_anyof(schema):
    """Exact rewrite of the generated single-branch support conjunction.

    Prove that parent and branch are identical closed, fully required objects,
    apart from object title annotations and support-array minItems floors. Their
    conjunction is then the parent with max(parent floor, branch floor). Refuse
    any other difference; this is intentionally not a general schema optimizer.
    The caller's schema is never mutated, including on a later proof failure.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    def fail():
        raise SchemaProjectionError("single_support_anyof_not_equivalent") from None

    def validate(value):
        try:
            Draft202012Validator.check_schema(value)
        except (SchemaError, TypeError, ValueError):
            fail()

    if type(schema) is not dict:
        fail()
    validate(schema)
    result = deepcopy(schema)
    support_fields = ("evidence_ids", "parent_claim_ids")
    object_keys = {"type", "properties", "required", "additionalProperties", "title"}
    for node in list(nodes(result)):
        branches = node.get("anyOf", [])
        if len(branches) != 1 or not set(support_fields) <= node.get("properties", {}).keys():
            continue
        parent = {key: deepcopy(value) for key, value in node.items() if key != "anyOf"}
        branch = deepcopy(branches[0])
        if not isinstance(branch, dict):
            fail()
        for value in (parent, branch):
            if (not set(value) <= object_keys or value.get("type") != "object"
                    or value.get("additionalProperties") is not False
                    or set(value.get("required", [])) != set(value.get("properties", {}))):
                fail()
        # Scope/evaluation-dependent keywords are outside this local proof.
        for value in (parent, branch):
            if any(any(key in sub for key in ("$id", "$anchor", "$dynamicAnchor", "$dynamicRef",
                    "unevaluatedProperties", "unevaluatedItems")) for sub in nodes(value)):
                fail()
        normalized_parent, normalized_branch = deepcopy(parent), deepcopy(branch)
        normalized_parent.pop("title", None)
        normalized_branch.pop("title", None)
        floors = {}
        for name in support_fields:
            left = normalized_parent["properties"].get(name)
            right = normalized_branch["properties"].get(name)
            if not isinstance(left, dict) or not isinstance(right, dict):
                fail()
            values = []
            for prop in (left, right):
                if prop.get("type") != "array":
                    fail()
                minimum = prop.pop("minItems", 0)
                if type(minimum) is not int or minimum < 0:
                    fail()
                values.append(minimum)
            floors[name] = max(values)
        # Python equality conflates true with 1. Use JSON-sensitive structural
        # equality so enum/const differences can never pass the proof.
        try:
            same = json.dumps(normalized_parent, sort_keys=True, allow_nan=False) == json.dumps(
                normalized_branch, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            fail()
        if not same:
            fail()
        if not any(floors.values()):
            fail()
        for name, minimum in floors.items():
            prop = parent["properties"][name]
            if minimum > prop.get("maxItems", minimum):
                fail()
            # Zero is the default; avoid adding a redundant floor to untouched
            # fields. Keep explicit parent/branch zero floors when present.
            if minimum or "minItems" in prop or "minItems" in branch["properties"][name]:
                prop["minItems"] = minimum
        node.clear()
        node.update(parent)
    validate(result)
    return result


def single_support_anyof_count(schema):
    return sum(len(node.get("anyOf", [])) == 1
        and {"evidence_ids", "parent_claim_ids"} <= node.get("properties", {}).keys()
        for node in nodes(schema))


def collapse_redundant_support_anyof(schema):
    """Remove a support OR only with an exact parent-object witness branch.

    P AND (P OR Q) is P. PARENT_REQUIRED generation supplies that witness;
    ordinary evidence-or-parent support does not. Preserve every parent bound,
    enum and reference. Refuse scope-sensitive schemas and pointers into branches
    so deleting a subtree cannot change reference resolution or evaluation.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    def fail():
        raise SchemaProjectionError("redundant_support_anyof_not_equivalent") from None

    if type(schema) is not dict:
        fail()
    try:
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError):
        fail()
    definitions = schema.get("$defs", {})
    for node in nodes(schema):
        if any(key in node for key in ("$id", "$anchor", "$dynamicAnchor", "$dynamicRef",
                                       "unevaluatedProperties", "unevaluatedItems")):
            fail()
        if "$ref" in node:
            ref = node["$ref"]
            if (not isinstance(ref, str) or not ref.startswith("#/$defs/")
                    or "/" in ref[len("#/$defs/"):]
                    or "~" in ref[len("#/$defs/"):]
                    or ref[len("#/$defs/"):] not in definitions):
                fail()
    result = deepcopy(schema)
    support = {"evidence_ids", "parent_claim_ids"}
    for node in list(nodes(result)):
        branches = node.get("anyOf", [])
        if len(branches) != 2 or not support <= node.get("properties", {}).keys():
            continue
        parent = {key: deepcopy(value) for key, value in node.items() if key != "anyOf"}
        if (parent.get("type") != "object" or parent.get("additionalProperties") is not False
                or set(parent.get("required", [])) != set(parent["properties"])):
            fail()
        comparison = deepcopy(parent)
        comparison.pop("title", None)
        witnesses = []
        for branch in branches:
            if type(branch) is not dict:
                fail()
            branch = deepcopy(branch)
            branch.pop("title", None)
            # Python's equality conflates true and 1 in enums/const values.
            witnesses.append(json.dumps(branch, sort_keys=True, allow_nan=False)
                             == json.dumps(comparison, sort_keys=True, allow_nan=False))
        if any(witnesses):
            node.clear()
            node.update(parent)
    return result


def schema_measurement(schema):
    raw = json.dumps(schema, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
