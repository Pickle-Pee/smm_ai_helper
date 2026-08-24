from datetime import datetime,timezone
from types import MappingProxyType
import pytest
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import claim,result,batch

class HostileList(list):
    calls=0
    def __iter__(self):type(self).calls+=1;raise AssertionError("iterated")
class HostileTuple(tuple):
    calls=0
    def __iter__(self):type(self).calls+=1;raise AssertionError("iterated")
class HostileDict(dict):
    calls=0
    def __iter__(self):type(self).calls+=1;raise AssertionError("iterated")
class HostileSet(set):
    calls=0
    def __iter__(self):type(self).calls+=1;raise AssertionError("iterated")
class HostileString(str):
    def __str__(self):raise AssertionError("formatted")
class HostileDatetime(datetime):pass

@pytest.mark.parametrize("value,cls",[(HostileList(),HostileList),(HostileTuple(),HostileTuple),(HostileSet(),HostileSet)])
def test_hostile_outer_containers_rejected_before_iteration(value,cls):
    cls.calls=0
    with pytest.raises(QualityGateContractError):result(claims=value)
    assert cls.calls==0
@pytest.mark.parametrize("value",[HostileDict(),MappingProxyType(HostileDict()),HostileString("x")])
def test_hostile_scalar_and_proxy_rejected_without_backing_access(value):
    HostileDict.calls=0
    with pytest.raises(QualityGateContractError):claim(value=value)
    assert HostileDict.calls==0
def test_datetime_subclass_rejected():
    with pytest.raises(QualityGateContractError):EvidenceRecord("evd_x",EvidenceSourceClass.UNKNOWN,"p",HostileDatetime.now(timezone.utc))
def test_wrong_nested_item_is_type_checked_before_hashing():
    class Bomb:
        def __hash__(self):raise AssertionError("hashed")
    with pytest.raises(QualityGateContractError):result(failure_reasons=[Bomb()])

def test_expected_registry_errors_are_normalized():
    class Registry:
        @property
        def version(self):raise KeyError("secret")
    with pytest.raises(QualityGateContractError,match="Registry validation failed"):QualityGateEvaluator(Registry()).evaluate(batch())
