"""Assertion-equivalent annotation removal for the provider, never persisted data."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .provider_schema import SchemaProjectionError

ANNOTATIONS = frozenset({"title", "description", "default", "examples"})
_MAPS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SINGLES = ("items", "additionalProperties", "contains", "propertyNames", "not",
            "if", "then", "else", "unevaluatedItems", "unevaluatedProperties", "contentSchema")


def strip_schema_annotations(schema):
    """Return an independent schema and removal count, or refuse before model I/O.

    Walk only Draft 2020-12 schema positions. Literal values and unknown extension
    data are opaque. References must point to retained local schema nodes; custom
    dialects/vocabularies and scope-changing IDs are outside this proof.
    """
    try:
        if type(schema) not in (dict, bool):
            raise ValueError
        # Ensure finite JSON, and turn cycles/depth failures into a safe refusal.
        json.dumps(schema, allow_nan=False)
        Draft202012Validator.check_schema(schema)
        result = deepcopy(schema)
        paths, references = set(), []
        removed = 0

        def walk(node, path):
            nonlocal removed
            paths.add(path)
            if type(node) is bool:
                return
            if "$vocabulary" in node or any(k in node for k in ("$id", "$dynamicRef")):
                raise ValueError
            if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError
            if "$ref" in node:
                references.append(node["$ref"])
            for key in ANNOTATIONS:
                if key in node:
                    del node[key]
                    removed += 1
            for key in _MAPS:
                for name, child in node.get(key, {}).items():
                    walk(child, (*path, key, name))
            for key in _LISTS:
                for index, child in enumerate(node.get(key, [])):
                    walk(child, (*path, key, str(index)))
            for key in _SINGLES:
                if key in node:
                    walk(node[key], (*path, key))

        walk(result, ())
        for ref in references:
            if ref == "#":
                continue
            if not ref.startswith("#/") or "%" in ref:
                raise ValueError
            target = tuple(part.replace("~1", "/").replace("~0", "~") for part in ref[2:].split("/"))
            if target not in paths:
                raise ValueError
        Draft202012Validator.check_schema(result)
        return result, removed
    except (SchemaError, TypeError, ValueError, RecursionError, AttributeError):
        raise SchemaProjectionError("annotation_projection_not_equivalent") from None
