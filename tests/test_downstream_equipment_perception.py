"""Future perception research does not establish an equipment condition."""
import pytest

from app.module_execution.executors.common import StatementSemanticsError
from app.module_execution.executors.downstream_fidelity import validate_leaf


OWNER = ('участники выполняют практические задания и получают письменную обратную связь; '
         'для занятий не требуется профессиональное оборудование.')
ACTUAL = ('Собрать письменную обратную связь по формату практических заданий и ощущению '
          'доступности без профессионального оборудования.')
RESEARCH = (
    ACTUAL,
    'Получить качественную обратную связь по формату практических заданий и ощущению доступности без оборудования.',
    'Собрать обратную связь по формату практических заданий и ощущению доступности без профессионального оборудования.',
    'Collect written feedback on the format of practical tasks and perceived accessibility without professional equipment.',
    'Gather qualitative feedback on the format of practice assignments and perceived accessibility without equipment.',
    'Collect feedback on format of practical assignments and perceived accessibility without any equipment.',
    '  ' + ACTUAL.upper() + '  ',
    ACTUAL[:-1],
)


def test_actual_future_collection_is_not_a_current_product_condition():
    validate_leaf(ACTUAL, owner=(OWNER,))


@pytest.mark.parametrize('text', RESEARCH)
def test_bounded_perception_collection_remains_a_research_plan(text):
    validate_leaf(text)


@pytest.mark.parametrize('text', RESEARCH)
def test_research_does_not_authorize_public_copy(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, owner=(OWNER,), copy_field=True)


@pytest.mark.parametrize('text', RESEARCH)
@pytest.mark.parametrize('quote', ['"', "'"])
def test_quoted_research_is_not_an_owner_product_assertion(text, quote):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(quote + text.strip() + quote, owner=(OWNER,))


@pytest.mark.parametrize('text', RESEARCH)
@pytest.mark.parametrize('extra', [
    ' Курс включает персональный разбор.',
    ' Демонстрационный образец показывает формат обратной связи.',
    ' Вы получите профессиональные навыки.',
    ' Курс доступен без оборудования.',
    ' Это подтверждает эффективность курса.',
])
def test_collection_cannot_launder_appended_claims(text, extra):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text.strip() + extra, owner=(OWNER,))


@pytest.mark.parametrize('text', [
    'Подтвердить, что курс доступен без профессионального оборудования.',
    'Аудитория подтверждает доступность без оборудования.',
    'Исследование доказало доступность без профессионального оборудования.',
    'Сообщение: обучение без профессионального оборудования доступно.',
    'Собрать письменную обратную связь по формату практических заданий и ощущению доступности без профессионального оборудования, чтобы подтвердить результативность курса.',
])
def test_results_and_positive_criteria_still_require_owner_truth(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, owner=(OWNER,))


def test_complete_owner_scope_and_qualifier_guard_are_unchanged():
    validate_leaf(OWNER, owner=(OWNER,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Обучение без оборудования доступно.', owner=(OWNER,))
