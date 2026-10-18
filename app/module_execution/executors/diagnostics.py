"""Closed, value-free metadata for internal statement rejection telemetry."""

EVIDENCE_CATEGORIES = frozenset({
    "product", "target_or_target_hypothesis", "product_truth", "existing_proof",
    "customer_job_or_need", "relevant_alternative",
})


def statement_metadata(index, statement, local, allowed_outputs):
    # Neither arbitrary labels nor evidence IDs may enter this event.
    categories = sorted({item.input_key if item.input_key in EVIDENCE_CATEGORIES else "other"
                         for eid in statement.evidence_ids for item in (local[eid],)})
    return {
        "output_index": index,
        "output_name": statement.output_name if statement.output_name in allowed_outputs else "other",
        "kind": statement.kind if statement.kind in {
            "OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"} else "other",
        "evidence_categories": categories,
    }
