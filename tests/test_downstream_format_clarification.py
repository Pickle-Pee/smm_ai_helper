import pytest

from app.module_execution.executors.downstream_fidelity import validate_leaf
from app.module_execution.executors.common import StatementSemanticsError
from app.module_registry import ModuleId
from tests.test_strategy_intelligence import run, valid_request


QUESTIONS = (
    'Уточнить у владельца содержание заданий и формат обратной связи, чтобы избежать недопонимания с домашними заданиями или персональными разбором.',
    'Провести качественные беседы с представителями аудитории, чтобы понять ожидания от письменной обратной связи и различия с персональным разбором.',
)


@pytest.mark.parametrize('text', QUESTIONS)
def test_owner_clarification_and_audience_comparison_do_not_assert_personal_delivery(text):
    validate_leaf(text)


@pytest.mark.parametrize('text', QUESTIONS)
@pytest.mark.parametrize('module,name', [
    (ModuleId.VIRTUAL_CMO, 'strategic_priorities'),
    (ModuleId.EXPERIMENTS, 'mechanism'),
])
def test_normal_executor_preserves_clarification_without_owner_fact_selection(text, module, name):
    def inject(payload, data):
        row = next(row for row in payload['outputs'] if row['output_name'] == name)
        row.update(text=text, evidence_ids=[])
    result = run(valid_request(module), inject)
    assert next(row for row in result.payload['outputs'] if row['output_name'] == name)['text'] == text


@pytest.mark.parametrize('text', QUESTIONS)
@pytest.mark.parametrize('extra', [
    ' Курс включает персональный разбор.',
    ' Демонстрационный образец показывает формат обратной связи.',
    ' Вы получите уверенность в фотографии.',
    ' Обучение без оборудования доступно.',
])
def test_clarification_does_not_authorize_appended_product_or_demo_claim(text, extra):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + extra)


@pytest.mark.parametrize('text', [
    'Курс включает персональный разбор.',
    'Аудитория понимает письменную обратную связь как персональный разбор.',
    'Провести беседы: курс включает персональный разбор.',
    'Уточнить у владельца: курс включает персональный разбор.',
])
def test_comparison_context_never_confirms_current_personal_format(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text)
