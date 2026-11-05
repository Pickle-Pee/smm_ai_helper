"""Product promises and demonstration witnesses survive downstream boundaries."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.marketing_orchestrator.quality_gates.contracts import EvidenceSourceClass
from app.module_execution.executors.common import ExecutorOutputError, SemanticRule, StatementSemanticsError
from app.module_execution.executors.downstream_fidelity import selected_sources, validate_leaf, validate_limitation
from app.module_registry import ModuleId
from tests.test_module_executors import fact
from tests.test_strategy_intelligence import run, valid_request


PROMISE = 'Сообщение «Курс Линия — практика с письменной обратной связью: получите понятное направление для следующего упражнения».'
TRUTH = 'Участники выполняют практические задания и получают письменную обратную связь.'
DEMO = 'Демонстрационный образец показывает сравнение снимков.'
DEMO_CLAIM = 'Существующее демонстрационное proof демонстрирует формат обратной связи.'
DEMO_LIMITATION = ('Существующее доказательство ограничено демонстрационным образцом '
                   'и не подтверждает масштабную эффективность акцента.')
DEMO_LIMITATION_EN = ('Existing evidence is limited to a demonstration sample '
                      'and does not prove the effectiveness of the course.')


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


def limitation_request(module, role='existing_proof', value=DEMO):
    req = valid_request(module)
    facts = req.context_packet.known_facts
    if role is not None:
        facts = (*facts, fact(role, value))
    return replace(req, context_packet=replace(req.context_packet, known_facts=facts))


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
@pytest.mark.parametrize('text', [
    DEMO_LIMITATION,
    'Демонстрационный образец не доказывает эффективность курса.',
    DEMO_LIMITATION + ' Демонстрационный образец не подтверждает эффективность обучения.',
    DEMO_LIMITATION_EN,
    'The demonstration sample does not confirm the effectiveness of training.',
    DEMO_LIMITATION_EN + ' The demonstration sample does not prove large-scale effectiveness of training.',
])
def test_actual_executors_accept_closed_negative_demo_coverage_as_global_limitation(module, text):
    def inject(payload, data):
        payload['limitations'] = [text]
    result = run(limitation_request(module), inject)
    assert text in result.payload['limitations']
    assert result.normalized_result.claims


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
@pytest.mark.parametrize('role,value', [
    (None, DEMO), ('product_truth', DEMO), ('target_or_target_hypothesis', DEMO),
    ('existing_proof', 'Собраны ответы аудитории.'),
    ('existing_proof', 'Existing proof shows feedback format.'),
])
def test_actual_limitation_requires_request_local_demo_proof_not_owner_or_hypothesis_parent(module, role, value):
    def inject(payload, data):
        payload['limitations'] = [DEMO_LIMITATION]
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module, role, value), inject)


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_english_negative_confirm_clause_requires_witness_even_without_old_positive_verb_signal(module):
    def inject(payload, data):
        payload['limitations'] = ['The demonstration sample does not confirm the effectiveness of training.']
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module, role=None), inject)


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
@pytest.mark.parametrize('source', [
    'Демонстрационный образец отсутствует.',
    'Демонстрационный образец не предоставлен.',
    'No demonstration sample exists.',
    'The demonstration sample is not available.',
    'Создать демонстрационный образец, который показывает сравнение снимков.',
    'Проверить, показывает ли демонстрационный образец сравнение снимков.',
    'Check whether the demonstration sample shows a comparison.',
    'Hypothesis: the demonstration sample shows a comparison.',
    'The demonstration sample will show a comparison.',
    'Демонстрационный образец',
    'Демонстрационный образец показывает сравнение снимков, если его создать.',
    'The demonstration sample shows a comparison if we create it.',
    'Демонстрационный образец показывает сравнение, если мы его создадим.',
    'The demo shows the comparison if created.',
    'The demonstration sample shows a comparison when created.',
    'The demonstration sample shows a comparison once created.',
    'The demonstration sample shows a comparison after creation.',
    'The demonstration sample is available when created.',
    'Демонстрационный образец показывает сравнение снимков, когда будет готов.',
    'Демонстрационный образец показывает сравнение снимков, когда только создадут.',
    'Демонстрационный образец показывает сравнение снимков?',
    'The demonstration sample shows a comparison?',
])
def test_actual_limitation_cannot_infer_current_demo_from_absence_plan_question_or_bare_marker(module, source):
    def inject(payload, data):
        payload['limitations'] = [DEMO_LIMITATION]
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module, value=source), inject)


@pytest.mark.parametrize('source', [
    DEMO, 'Демонстрационный образец показывает вариант глазурования чаши.',
    'Предоставлен демонстрационный образец.', 'Имеется демонстрационный образец.',
    'The demonstration sample shows a comparison.', 'A provided demo illustrates a comparison.',
    'The demonstration sample is available.', 'Provided demonstration sample.',
])
def test_limitation_current_witness_uses_only_closed_complete_sources(source):
    local = {'demo': SimpleNamespace(input_key='existing_proof', value=source,
             record=SimpleNamespace(source_class=EvidenceSourceClass.FIRST_PARTY))}
    if 'illustrates' in source:
        # A valid but unsupported paraphrase does not expand this presence
        # recognizer; it is deliberately not general NLP existence inference.
        with pytest.raises(StatementSemanticsError):
            validate_limitation(DEMO_LIMITATION, local)
    else:
        validate_limitation(DEMO_LIMITATION, local)


@pytest.mark.parametrize('source_class', [EvidenceSourceClass.EXTERNAL_PRIMARY, EvidenceSourceClass.EXTERNAL_SECONDARY])
def test_limitation_witness_must_be_typed_first_party(source_class):
    local = {'demo': SimpleNamespace(input_key='existing_proof', value=DEMO,
             record=SimpleNamespace(source_class=source_class))}
    with pytest.raises(StatementSemanticsError) as caught:
        validate_limitation(DEMO_LIMITATION, local)
    assert caught.value.rule is SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_actual_limitation_rejects_external_class_even_when_demo_role_is_present(module, monkeypatch):
    from app.module_execution.executors import experiments, virtual_cmo
    implementation = virtual_cmo if module is ModuleId.VIRTUAL_CMO else experiments
    original = implementation.first_party_evidence
    def external(*args, **kwargs):
        return tuple(replace(item, record=replace(item.record, source_class=EvidenceSourceClass.EXTERNAL_PRIMARY))
                     if item.input_key == 'existing_proof' else item
                     for item in original(*args, **kwargs))
    monkeypatch.setattr(implementation, 'first_party_evidence', external)
    def inject(payload, data):
        payload['limitations'] = [DEMO_LIMITATION]
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module), inject)


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
@pytest.mark.parametrize('text', [
    DEMO_LIMITATION + ' Вы научитесь уверенно фотографировать.',
    DEMO_LIMITATION + ' Демонстрационный образец показывает формат курса.',
    DEMO_LIMITATION_EN + ' The course is effective.',
    'The demonstration sample does not confirm the effectiveness of training. You will master photography.',
    'Гипотеза: ' + DEMO_CLAIM,
    DEMO,
    DEMO_CLAIM,
    'The existing demonstration proves the course is effective.',
    DEMO_LIMITATION + ' Демонстрационный образец не подтверждает эффективность обучения. '
    + 'Демонстрационный образец не доказывает эффективность курса.',
])
def test_negative_coverage_exception_never_grants_positive_or_appended_claim_authority(module, text):
    def inject(payload, data):
        payload['limitations'] = [text]
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module), inject)


@pytest.mark.parametrize('module,location', [
    (ModuleId.VIRTUAL_CMO, 'text'), (ModuleId.VIRTUAL_CMO, 'items'),
    (ModuleId.VIRTUAL_CMO, 'assumptions'), (ModuleId.EXPERIMENTS, 'text'),
    (ModuleId.EXPERIMENTS, 'intervention'), (ModuleId.EXPERIMENTS, 'assumptions'),
])
def test_global_limitation_rule_does_not_authorize_other_output_locations(module, location):
    def inject(payload, data):
        if location == 'assumptions':
            payload['assumptions'] = [DEMO_LIMITATION]
        elif location == 'intervention':
            payload['experiments'][0]['intervention'] = DEMO_LIMITATION
        elif location == 'items':
            payload['outputs'][0]['items'] = [DEMO_LIMITATION]
        else:
            payload['outputs'][0]['text'] = DEMO_LIMITATION
    with pytest.raises(ExecutorOutputError):
        run(limitation_request(module), inject)
