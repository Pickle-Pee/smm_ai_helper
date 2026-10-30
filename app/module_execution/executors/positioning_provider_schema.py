"""Experimental generation envelope; never an acceptance/validation schema."""


def minimal_positioning_schema():
    """Keep wire shape, required keys and primitive types; defer rules locally.

    Deliberately no refs, unions, enums, annotations or value/length constraints.
    Return a fresh tree so provider code cannot mutate another invocation.
    """
    def strings():
        return {"type": "array", "items": {"type": "string"}}

    def closed(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    statement = closed({
        "output_name": {"type": "string"}, "text": {"type": "string"},
        "kind": {"type": "string"}, "confidence": {"type": "string"},
        "evidence_ids": strings(), "parent_claim_ids": strings(),
    })
    return closed({"assumptions": strings(), "limitations": strings(),
                   "outputs": {"type": "array", "items": statement}})
