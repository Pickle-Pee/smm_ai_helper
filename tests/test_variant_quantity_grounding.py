import pytest

from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
from app.module_execution.executors.numeric_quantity import has_numeric_quantity
from app.module_registry import ModuleId
from tests.test_strategy_intelligence import run, valid_request


ACTUAL_METHOD = ('Провести качественные беседы/интервью с представителями целевой аудитории и показать им '
    'двевариантные формулировки сообщения: нейтральную, основанную на подтверждённых условиях, и тестовую — '
    'с акцентом на ориентире практики через письменную обратную связь; собрать понимание, причины предпочтения и сомнения.')


@pytest.mark.parametrize('text', [ACTUAL_METHOD, 'Подготовить двухвариантный тест.',
    'Сравнить двевариантные формулировки.', 'Prepare a two-variant comparison.', 'Compare twovariants.'])
def test_explicit_cardinal_variant_noun_or_adjective_is_a_quantity(text):
    assert has_numeric_quantity(text)


@pytest.mark.parametrize('text', ['Вариантные формулировки сообщения.', 'Compare variant messages.',
    'Studio Two offers variants.', 'Someone prefers variants.', 'two of the variants', 'two...variant'])
def test_variant_unit_does_not_expand_cardinal_substring_or_gap_rules(text):
    assert not has_numeric_quantity(text)


@pytest.mark.parametrize('module,name', [(ModuleId.EXPERIMENTS, 'test_method'),
                                       (ModuleId.VIRTUAL_CMO, 'resource_priorities')])
def test_actual_unprovided_variant_count_rejects_before_canonical_persistence(module, name):
    def inject(payload, data):
        next(row for row in payload['outputs'] if row['output_name'] == name)['text'] = ACTUAL_METHOD
    with pytest.raises(ExecutorOutputError) as caught:
        run(valid_request(module), inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
