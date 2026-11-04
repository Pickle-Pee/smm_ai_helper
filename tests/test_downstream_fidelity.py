"""Product promises and demonstration witnesses survive downstream boundaries."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.marketing_orchestrator.quality_gates.contracts import EvidenceSourceClass
from app.module_execution.executors.common import ExecutorOutputError, SemanticRule, StatementSemanticsError
from app.module_execution.executors.downstream_fidelity import selected_sources, validate_leaf
from app.module_registry import ModuleId
from tests.test_module_executors import fact
from tests.test_strategy_intelligence import run, valid_request


PROMISE = 'Сообщение «Курс Линия — практика с письменной обратной связью: получите понятное направление для следующего упражнения».'
TRUTH = 'Участники выполняют практические задания и получают письменную обратную связь.'
DEMO = 'Демонстрационный образец показывает сравнение снимков.'
DEMO_CLAIM = 'Существующее демонстрационное proof демонстрирует формат обратной связи.'


@pytest.mark.parametrize('text', [
    PROMISE, 'Гипотеза: ' + PROMISE,
    'Вы научитесь уверенно фотографировать.', 'На курсе станете профессионалом.',
    'Сообщение: «You will gain confidence in photography».',
    'Copy: "You can master photography".',
    TRUTH + ' ' + PROMISE,
    'Не обещать «Вы научитесь фотографировать». Курс: вы получите уверенность.',
    'Conduct interviews about the course and you will master photography using the data.',
    'Проведите интервью о курсе — вы научитесь фотографировать на основе данных.',
    'Проведите интервью о курсе — получите данные и уверенность в фотографии.',
    'Learn photography with confidence.', 'Master photography.',
])
def test_product_outcome_not_proven_by_an_appended_owner_quote(text):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(TRUTH,), demo=(DEMO,))
    assert caught.value.rule is SemanticRule.CUSTOMER_PROMISE_REQUIRES_OWNER_SOURCE


@pytest.mark.parametrize('text', [
    'Гипотеза: аудитории важен ориентир для следующей практики.',
    'Исследовать, хочет ли аудитория научиться фотографировать.',
    'Проведите интервью о курсе — получите данные для проверки гипотезы.',
    'Conduct interviews about the course and you will get data.',
    "Conduct interviews about the course and you'll get data.",
    'После опроса вы получите данные о реакции аудитории.',
    'Research what beginners want to learn in the course.',
    "Ask the audience's participants what they want to learn.",
    'If customers learn whether the course fits their needs, record the response.',
    'Customer goal: learn photography.',
    'Learn from pilot feedback about the course.',
    'Не обещать «На курсе вы научитесь фотографировать».',
    'Do not promise "you will master photography".',
    'Создать демонстрационный образец, который показывает сравнение снимков.',
    'Check whether a new demo shows the intended comparison.',
    'Демонстрировать разные варианты сообщения.',
])
def test_research_goals_and_closed_counterfactuals_are_not_product_promises(text):
    validate_leaf(text)


def test_exact_selected_owner_copy_preserves_the_complete_condition():
    source = 'На курсе вы получите письменную обратную связь. Изделия забирают в другой день.'
    validate_leaf(source, owner=(source,))
    validate_leaf('Сообщение: «' + source + '»', owner=(source,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(source.split('.')[0] + '.', owner=(source,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(source + ' И понятное направление дальнейшей практики.', owner=(source,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(source, demo=(source,))


@pytest.mark.parametrize('text', [
    'Участники научатся уверенно фотографировать.',
    'Курс обеспечит понятное направление для следующего упражнения.',
    'Participants will master photography.',
])
def test_control_and_treatment_cannot_publish_third_person_outcome_copy(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, copy_field=True)
    # A desired outcome can remain a tentative planning hypothesis elsewhere;
    # this bounded guard does not assert that every arbitrary prose claim is safe.
    validate_leaf('Гипотеза для проверки: ' + text)


@pytest.mark.parametrize('text', ['Learn photography with confidence.', 'Master photography.',
                               'Customer goal: learn photography. Master photography with confidence.',
                               'Try the course. Master photography.',
                               'Customer goal: learn photography.'])
def test_actual_treatment_distinguishes_customer_copy_from_an_explicit_goal(text):
    def inject(payload, data):
        next(row for row in payload['outputs'] if row['output_name'] == 'treatment')['text'] = text
    if text == 'Customer goal: learn photography.':
        assert run(valid_request(ModuleId.EXPERIMENTS), inject).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError):
            run(valid_request(ModuleId.EXPERIMENTS), inject)


@pytest.mark.parametrize('selected', [(), (DEMO,)])
def test_demo_paraphrase_does_not_establish_service_format(selected):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(DEMO_CLAIM, demo=selected)
    assert caught.value.rule is SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE


def test_demo_requires_actual_selection_and_exact_whole_leaf():
    with pytest.raises(StatementSemanticsError):
        validate_leaf(DEMO)
    validate_leaf(DEMO, demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(DEMO + ' Это доказывает формат курса.', demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Создать новый образец. Существующее demo показывает формат.', demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Create a demo. The demonstration shows feedback format.', demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Check whether buyers value the demonstration which shows feedback format.', demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Создать новый demo, который доказывает, что курс эффективен.', demo=(DEMO,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Подготовить proof, подтверждающий, что участники получают персональную обратную связь.', demo=(DEMO,))


def test_audience_and_demo_are_not_typed_owner_truth():
    def source(role):
        return SimpleNamespace(input_key=role, value=TRUTH,
            record=SimpleNamespace(source_class=EvidenceSourceClass.FIRST_PARTY))
    row = SimpleNamespace(evidence_ids=['audience', 'demo'])
    local = {'audience': source('target_or_target_hypothesis'), 'demo': source('existing_proof'),
             'owner': source('product_truth')}
    owner, demo = selected_sources(row, local)
    assert owner == () and demo == (TRUTH,)
    row.evidence_ids.append('owner')
    assert selected_sources(row, local)[0] == (TRUTH,)


@pytest.mark.parametrize('module,location', [
    (ModuleId.VIRTUAL_CMO, 'text'), (ModuleId.VIRTUAL_CMO, 'items'),
    (ModuleId.VIRTUAL_CMO, 'assumptions'), (ModuleId.VIRTUAL_CMO, 'limitations'),
    (ModuleId.EXPERIMENTS, 'text'), (ModuleId.EXPERIMENTS, 'intervention'),
    (ModuleId.EXPERIMENTS, 'minimum_required_inputs'), (ModuleId.EXPERIMENTS, 'expected_signal'),
    (ModuleId.EXPERIMENTS, 'assumptions'), (ModuleId.EXPERIMENTS, 'limitations'),
])
def test_real_executor_cannot_move_promise_into_a_different_public_leaf(module, location):
    def inject(payload, data):
        if location == 'text':
            row = next(row for row in payload['outputs']
                       if row['output_name'] == ('treatment' if module is ModuleId.EXPERIMENTS else 'strategic_diagnosis'))
            row['text'] = PROMISE
        elif location == 'items':
            payload['outputs'][0]['items'] = [PROMISE]
        elif location in {'assumptions', 'limitations'}:
            payload[location] = [PROMISE]
        else:
            payload['experiments'][0][location] = [PROMISE] if location == 'minimum_required_inputs' else PROMISE
    with pytest.raises(ExecutorOutputError):
        run(valid_request(module), inject)


@pytest.mark.parametrize('cite', [False, True])
def test_cmo_existing_demo_claim_needs_its_own_actual_selected_witness(cite):
    req = valid_request(ModuleId.VIRTUAL_CMO)
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact('existing_proof', DEMO))))
    def inject(payload, data):
        row = next(row for row in payload['outputs'] if row['output_name'] == 'strategic_diagnosis')
        demo_id = next(source['evidence_id'] for source in data['local_evidence'] if source['input_key'] == 'existing_proof')
        row['items'] = [DEMO]
        row['evidence_ids'] = [demo_id] if cite else []
    if cite:
        assert run(req, inject).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError):
            run(req, inject)


@pytest.mark.parametrize('role,cite,allowed', [('product_truth', True, True),
    ('product_truth', False, False), ('existing_proof', True, False),
    ('target_or_target_hypothesis', True, False)])
def test_actual_treatment_owner_witness_is_typed_and_selected_per_output(role, cite, allowed):
    source = 'На курсе вы получите письменную обратную связь. Изделия забирают в другой день.'
    req = valid_request(ModuleId.EXPERIMENTS)
    req = replace(req, context_packet=replace(req.context_packet, known_facts=(fact(role, source),)))
    def inject(payload, data):
        row = next(row for row in payload['outputs'] if row['output_name'] == 'treatment')
        row['text'] = source
        identity = next(item['evidence_id'] for item in data['local_evidence'] if item['input_key'] == role)
        row['evidence_ids'] = [identity] if cite else []
    if allowed:
        assert run(req, inject).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError):
            run(req, inject)


def test_exact_foreign_attribution_is_not_an_owner_source_for_new_copy():
    foreign = 'The competitor site states: You will learn photography.'
    validate_leaf(foreign, comparisons=(foreign,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('You will learn photography.', comparisons=(foreign,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(foreign + ' Our course: you will master photography.', comparisons=(foreign,))
