"""Full-result execution acceptance; partial claims cannot cross this boundary."""
from app.module_registry import ModuleResultStatus


def fully_accepted(result, accepted_result_ids, accepted_claim_ids):
    normalized = result.normalized_result
    claims = {claim.claim_id for claim in normalized.claims}
    return (
        normalized.module_status in {ModuleResultStatus.PASS, ModuleResultStatus.PASS_WITH_LIMITATIONS}
        and normalized.result_id in accepted_result_ids
        and claims == claims.intersection(accepted_claim_ids)
    )
