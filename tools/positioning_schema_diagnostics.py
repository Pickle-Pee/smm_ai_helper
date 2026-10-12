"""Schema-only ablations and content-free structural measurements.

These are diagnostic transformations, never provider-compatibility certification
or replacement server contracts. Traversal visits schema positions, not JSON literals.
"""
from collections import Counter
from copy import deepcopy

from app.module_execution.executors.provider_schema import (
    MAPS, LISTS, SINGLES, children, nodes, collapse_single_support_anyof,
)


SCHEMA_CASES = (
    "schema_no_support_anyof", "schema_no_string_bounds", "schema_no_array_bounds",
    "schema_no_support_enums", "schema_no_semantic_enums", "schema_inline_refs",
    "schema_flatten_output_union", "schema_no_annotations", "schema_collapse_single_support_anyof",
)
KEYWORDS = ("anyOf", "oneOf", "allOf", "$ref", "$defs", "enum", "const", "type",
            "minItems", "maxItems", "minLength", "maxLength", "required", "additionalProperties",
            "not", "dependentRequired", "dependentSchemas", "if", "then", "else")
ANNOTATIONS = ("title", "description", "default", "examples")
MAX_EXPANDED_NODES = 50000


class SchemaDiagnosticError(ValueError):
    pass


def is_support_or(node):
    properties = node.get("properties", {})
    branches = node.get("anyOf", [])
    return (node.get("type") == "object" and {"evidence_ids", "parent_claim_ids"} <= properties.keys()
            and bool(branches) and all(isinstance(branch, dict) and branch.get("type") == "object"
                and set(branch.get("properties", {})) == set(properties)
                and any(branch["properties"][key].get("minItems", 0) > 0
                        for key in ("evidence_ids", "parent_claim_ids")) for branch in branches))


def inline_refs(schema):
    """Equivalent local acyclic ref expansion, bounded and without remote lookup.

    Ref siblings with conflicting constraints are rejected instead of merged into
    an accidentally looser schema. Recursive schemas can be supported by OpenAI;
    this diagnostic transformation deliberately cannot expand them infinitely.
    """
    visited = 0

    def resolve(ref):
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise SchemaDiagnosticError("nonlocal_or_unsupported_ref")
        target = schema
        try:
            for token in ref[2:].split("/"):
                target = target[token.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise SchemaDiagnosticError("unresolved_ref") from None
        if not isinstance(target, dict):
            raise SchemaDiagnosticError("invalid_ref_target")
        return target

    def expand(node, stack=()):
        nonlocal visited
        visited += 1
        if visited > MAX_EXPANDED_NODES:
            raise SchemaDiagnosticError("ref_expansion_limit")
        if "$ref" in node:
            ref = node["$ref"]
            if ref in stack:
                raise SchemaDiagnosticError("recursive_ref_not_expanded")
            result = expand(resolve(ref), (*stack, ref))
            siblings = expand({k: v for k, v in node.items() if k != "$ref"}, stack)
            if any(key in result and result[key] != value for key, value in siblings.items()):
                raise SchemaDiagnosticError("ref_sibling_conflict")
            return {**result, **siblings}
        result = deepcopy(node)
        result.pop("$defs", None)
        result.pop("definitions", None)
        for key in MAPS:
            if key in result:
                result[key] = {name: expand(child, stack) if isinstance(child, dict) else child
                               for name, child in result[key].items()}
        for key in LISTS:
            if key in result:
                result[key] = [expand(child, stack) if isinstance(child, dict) else child for child in result[key]]
        for key in SINGLES:
            if isinstance(result.get(key), dict):
                result[key] = expand(result[key], stack)
        return result

    return expand(schema)


def flatten_output_union(schema):
    """Relax only output-name/kind correlation; retain every other restriction.

    Keep original definitions intact, including now-unused subtype definitions.
    This isolates the outer selection; it cannot rule out processing of unused defs.
    """
    item = schema["properties"]["outputs"]["items"]
    alternatives = item.get("anyOf", [])
    if not alternatives:
        raise SchemaDiagnosticError("output_union_unavailable")
    definitions = []
    for alternative in alternatives:
        ref = alternative.get("$ref")
        if set(alternative) != {"$ref"} or not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise SchemaDiagnosticError("output_union_shape_changed")
        definitions.append(deepcopy(schema["$defs"][ref[len("#/$defs/"):]]))
    # Make every subtype's two discriminator schemas identical, then assert that
    # the remaining constraints match. No arbitrary first-branch simplification.
    for key in ("output_name", "kind"):
        values = {value for definition in definitions
            for value in definition["properties"][key].get("enum", [definition["properties"][key].get("const")])}
        if any(not isinstance(value, str) for value in values):
            raise SchemaDiagnosticError("output_discriminator_shape_changed")
        allowed = sorted(values)
        for definition in definitions:
            for node in nodes(definition):
                if key in node.get("properties", {}):
                    prop = node["properties"][key]
                    prop.pop("const", None)
                    prop["enum"] = allowed
    for definition in definitions:
        definition.pop("title", None)
    if any(definition != definitions[0] for definition in definitions[1:]):
        raise SchemaDiagnosticError("output_subtype_constraints_differ")
    schema["properties"]["outputs"]["items"] = definitions[0]
    return schema


def schema_variants(payload):
    """Deep independent copies; only text.format.schema changes in each case."""
    result = {}
    for case in SCHEMA_CASES:
        candidate = deepcopy(payload)
        schema = candidate["text"]["format"]["schema"]
        if case == "schema_collapse_single_support_anyof":
            candidate["text"]["format"]["schema"] = collapse_single_support_anyof(schema)
        elif case == "schema_inline_refs":
            candidate["text"]["format"]["schema"] = inline_refs(schema)
        elif case == "schema_flatten_output_union":
            flatten_output_union(schema)
        elif case == "schema_no_support_enums":
            for name in ("AllowedEvidenceId", "AllowedParentClaimId"):
                schema.get("$defs", {}).get(name, {}).pop("enum", None)
        else:
            for node in list(nodes(schema)):
                if case == "schema_no_support_anyof" and is_support_or(node):
                    node.pop("anyOf")
                elif case in ("schema_no_string_bounds", "schema_no_array_bounds", "schema_no_annotations"):
                    keys = {"schema_no_string_bounds": ("minLength", "maxLength"),
                            "schema_no_array_bounds": ("minItems", "maxItems"),
                            "schema_no_annotations": ANNOTATIONS}[case]
                    for key in keys:
                        node.pop(key, None)
                elif case == "schema_no_semantic_enums":
                    for name in ("output_name", "kind", "confidence"):
                        prop = node.get("properties", {}).get(name, {})
                        prop.pop("enum", None)
                        prop.pop("const", None)
        result[case] = candidate
    return result


def schema_metadata(schema):
    """Counts/closed flags only. No definition/property/enum/ref values returned."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    counts = Counter({key: 0 for key in KEYWORDS})
    objects = properties = enums = enum_chars = string_chars = type_unions = 0
    required_failures = additional_failures = support_ors = contradictions = 0
    large_enum_failures = single_anyofs = unsupported_compositions = 0
    for node in nodes(schema):
        counts.update(key for key in KEYWORDS if key in node)
        single_anyofs += len(node.get("anyOf", [])) == 1
        unsupported_compositions += sum(key in node for key in ("allOf", "not", "dependentRequired", "dependentSchemas", "if", "then", "else"))
        large_enum_failures += (len(node.get("enum", [])) > 250 and
            sum(len(value) for value in node["enum"] if isinstance(value, str)) > 15000)
        enums += len(node.get("enum", []))
        enum_chars += sum(len(value) for value in node.get("enum", []) if isinstance(value, str))
        string_chars += sum(len(name) for name in node.get("properties", {}))
        string_chars += sum(len(name) for name in node.get("$defs", {}))
        string_chars += sum(len(value) for value in node.get("enum", []) if isinstance(value, str))
        if isinstance(node.get("const"), str):
            string_chars += len(node["const"])
        type_unions += isinstance(node.get("type"), list)
        if node.get("type") == "object":
            objects += 1
            properties += len(node.get("properties", {}))
            required_failures += set(node.get("required", [])) != set(node.get("properties", {}))
            additional_failures += node.get("additionalProperties") is not False
        support_ors += is_support_or(node)
        for lower, upper in (("minItems", "maxItems"), ("minLength", "maxLength")):
            contradictions += lower in node and upper in node and node[lower] > node[upper]
    try:
        Draft202012Validator.check_schema(schema)
        valid = True
    except SchemaError:
        valid = False

    def depth(node, any_depth=0, container_depth=0, same_instance=False):
        any_depth += "anyOf" in node
        is_container = node.get("type") in ("object", "array")
        container_depth += is_container and not same_instance
        results = [(any_depth, container_depth)]
        for child in children(node, definitions=False):
            # Composition constrains the same JSON instance; only properties and
            # items introduce new container levels, not complete-object OR copies.
            composition = any(any(child is branch for branch in node.get(key, [])) for key in LISTS)
            results.append(depth(child, any_depth, container_depth, composition and is_container))
        return max(x[0] for x in results), max(x[1] for x in results)

    try:
        expanded = inline_refs(schema)
        any_depth, container_depth = depth(expanded)
        resolved_anyofs = sum("anyOf" in node for node in nodes(expanded))
        ref_expansion = "local_acyclic"
    except SchemaDiagnosticError:
        any_depth = container_depth = resolved_anyofs = None
        ref_expansion = "not_expanded"
    families = schema.get("$defs", {})
    return {
        "json_schema_valid": valid, "provider_compatibility": "not_verified",
        "root_is_object": schema.get("type") == "object", "root_anyof": "anyOf" in schema,
        "single_branch_anyof_nodes": single_anyofs,
        "unsupported_composition_occurrences": unsupported_compositions,
        "documented_limits_exceeded": {"properties": properties > 5000, "enum_values": enums > 1000,
            "string_characters": string_chars > 120000, "large_enum_characters": bool(large_enum_failures),
            "container_depth": container_depth > 10 if container_depth is not None else None},
        "keyword_counts": dict(counts), "definitions_count": len(families),
        "object_nodes": objects, "property_occurrences": properties,
        "enum_values_count": enums, "enum_value_characters": enum_chars,
        "schema_string_characters": string_chars, "type_list_unions": type_unions,
        "support_anyof_nodes": support_ors, "required_mismatch_nodes": required_failures,
        "additional_properties_mismatch_nodes": additional_failures,
        "contradictory_length_ranges": contradictions,
        "resolved_anyof_nodes": resolved_anyofs, "resolved_anyof_depth": any_depth, "resolved_container_depth": container_depth,
        "reference_expansion": ref_expansion,
        "support_allowlist_counts": [len(families.get(name, {}).get("enum", []))
                                    for name in ("AllowedEvidenceId", "AllowedParentClaimId")],
    }
