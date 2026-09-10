import pytest

from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import UTC, claim, result


CHAIN_SIZE=1100


def _claim_id(index):return f"clm_{index:04d}"


def _long_batch(direction="forward", *, cycle=False, short_cycle=False, split_results=False, multiple_roots=False):
    claims=[]
    evidence=EvidenceRecord("evd_root",EvidenceSourceClass.FIRST_PARTY,"root",UTC)
    for index in range(CHAIN_SIZE):
        if cycle:
            parent=(index-1)%CHAIN_SIZE if direction=="forward" else (index+1)%CHAIN_SIZE
            parents=(_claim_id(parent),);lineage=ClaimLineageType.DERIVES
        elif short_cycle:
            if index<CHAIN_SIZE-2:parents=(_claim_id(index+1),)
            elif index==CHAIN_SIZE-2:parents=(_claim_id(CHAIN_SIZE-1),)
            else:parents=(_claim_id(CHAIN_SIZE-2),)
            lineage=ClaimLineageType.DERIVES
        elif multiple_roots:
            if index<2:parents=();lineage=ClaimLineageType.ORIGINAL
            elif index==2:parents=(_claim_id(0),_claim_id(1));lineage=ClaimLineageType.DERIVES
            else:parents=(_claim_id(index-1),);lineage=ClaimLineageType.DERIVES
        else:
            root=0 if direction=="forward" else CHAIN_SIZE-1
            if index==root:parents=();lineage=ClaimLineageType.ORIGINAL
            else:
                parent=index-1 if direction=="forward" else index+1
                parents=(_claim_id(parent),);lineage=ClaimLineageType.DERIVES
        root_with_evidence=(not cycle and not short_cycle and index==(0 if direction=="forward" or multiple_roots else CHAIN_SIZE-1))
        claims.append(claim(_claim_id(index),confidence=Confidence.MEDIUM if not parents else Confidence.LOW,lineage_type=lineage,parent_claim_ids=parents,evidence_ids=("evd_root",) if root_with_evidence else ()))
    if not split_results:
        results=(result("res_chain",claims=claims,evidence=(evidence,) if not cycle and not short_cycle else ()),)
    else:
        left=tuple(claims[::2]);right=tuple(claims[1::2])
        root_id=0 if direction=="forward" else CHAIN_SIZE-1
        left_evidence=(evidence,) if root_id%2==0 else ();right_evidence=(evidence,) if root_id%2 else ()
        results=(result("res_left",claims=left,evidence=left_evidence),result("res_right",claims=right,evidence=right_evidence))
    source=list(results)
    built=EvaluationBatch("bat_long",source)
    source.reverse()
    return built,tuple(reversed(results))


@pytest.mark.parametrize("direction",("forward","reverse"))
def test_long_lineage_chain_is_total_in_both_id_directions(direction):
    batch,_=_long_batch(direction)
    first=QualityGateEvaluator().evaluate(batch);second=QualityGateEvaluator().evaluate(batch)
    assert first==second
    assert len(first.propagated_claim_contexts)==CHAIN_SIZE
    assert tuple(x.claim_id for x in first.propagated_claim_contexts)==tuple(sorted(x.claim_id for x in first.propagated_claim_contexts))
    leaf_id=_claim_id(CHAIN_SIZE-1 if direction=="forward" else 0)
    leaf={x.claim_id:x for x in first.propagated_claim_contexts}[leaf_id]
    assert leaf.evidence_ids==("evd_root",)
    assert leaf.effective_confidence is Confidence.LOW
    assert first.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert len(batch.results[0].claims)==CHAIN_SIZE


@pytest.mark.parametrize("direction",("forward","reverse"))
def test_long_lineage_cycle_is_a_contract_error(direction):
    batch,_=_long_batch(direction,cycle=True)
    with pytest.raises(QualityGateContractError,match="cycle"):
        QualityGateEvaluator().evaluate(batch)


def test_long_chain_ending_in_short_cycle_is_a_contract_error():
    batch,_=_long_batch(short_cycle=True)
    with pytest.raises(QualityGateContractError,match="cycle"):
        QualityGateEvaluator().evaluate(batch)


def test_reordered_results_and_multiple_roots_are_deterministic():
    batch,reversed_results=_long_batch("reverse",split_results=True)
    reordered=EvaluationBatch("bat_long",reversed_results)
    assert batch.batch_fingerprint==reordered.batch_fingerprint
    assert QualityGateEvaluator().evaluate(batch)==QualityGateEvaluator().evaluate(reordered)
    rooted,_=_long_batch(multiple_roots=True)
    out=QualityGateEvaluator().evaluate(rooted)
    assert len(out.propagated_claim_contexts)==CHAIN_SIZE
    assert {x.claim_id:x for x in out.propagated_claim_contexts}[_claim_id(CHAIN_SIZE-1)].evidence_ids==("evd_root",)
