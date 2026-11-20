"""Provider-only POSITIONING kind subset; canonical validation stays independent."""
from copy import deepcopy

from jsonschema import Draft202012Validator

from .provider_schema import SchemaProjectionError, nodes
from .support_schema import check_schema_bounds


KINDS = frozenset({"OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"})


def positioning_observation_schema(schema, *, minimal=False):
    """Exclude generated observations, without removing inference or source rules.

    Every complete-object support branch is visited. The minimal experiment's
    unconstrained kind string is intentionally narrowed too; unknown shapes fail
    before dispatch rather than silently leaving observations generatable.
    """
    if type(schema) is not dict:
        raise SchemaProjectionError("Unexpected POSITIONING schema contract")
    result = deepcopy(schema)
    count = 0
    for node in nodes(result):
        properties = node.get("properties", {})
        if type(properties) is not dict:
            raise SchemaProjectionError("Unexpected POSITIONING properties contract")
        if "kind" not in properties:
            continue
        kind = properties["kind"]
        if type(kind) is not dict or ("title" in kind and type(kind["title"]) is not str):
            raise SchemaProjectionError("Unexpected POSITIONING kind contract")
        if minimal and kind == {"type": "string"}:
            kind["enum"] = sorted(KINDS - {"OBSERVATION"})
        elif kind.get("type") == "string" and "enum" in kind and set(kind) <= {"type", "enum", "title"}:
            values = kind["enum"]
            if (not isinstance(values, list) or not values
                    or any(type(value) is not str or value not in KINDS for value in values)
                    or len(values) != len(set(values))):
                raise SchemaProjectionError("Unexpected POSITIONING kind contract")
            remaining = [value for value in values if value != "OBSERVATION"]
            if not remaining:
                raise SchemaProjectionError("Empty POSITIONING provider kind contract")
            kind["enum"] = remaining
        elif (kind.get("type") == "string" and type(kind.get("const")) is str
              and kind["const"] in KINDS - {"OBSERVATION"}
              and set(kind) <= {"type", "const", "title"}):
            pass
        else:
            raise SchemaProjectionError("Unexpected POSITIONING kind contract")
        count += 1
    if not count:
        raise SchemaProjectionError("Missing POSITIONING kind contract")
    check_schema_bounds(result)
    Draft202012Validator.check_schema(result)
    return result
