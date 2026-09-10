from __future__ import annotations
from .contracts import Confidence, FreshnessComparison
from .errors import QualityGateContractError

_ORDER={Confidence.UNKNOWN:0,Confidence.LOW:1,Confidence.MEDIUM:2,Confidence.HIGH:3}
def confidence_within_parent_ceiling(confidence,parents): return not parents or _ORDER[confidence] <= min(_ORDER[x] for x in parents)
def compare_observed_at(left,right):
    if left is None or right is None:return FreshnessComparison.UNKNOWN
    if left>right:return FreshnessComparison.NEWER
    if left<right:return FreshnessComparison.OLDER
    return FreshnessComparison.SAME

def merge_records_by_id(groups, id_attribute):
    """Identity-union immutable records, rejecting unequal stable-ID collisions."""
    merged={}
    for group in groups:
        for record in group:
            identity=getattr(record,id_attribute)
            existing=merged.get(identity)
            if existing is not None and existing!=record:raise QualityGateContractError(f"unequal {id_attribute} collision: {identity}")
            merged[identity]=record
    return tuple(merged[key] for key in sorted(merged))
