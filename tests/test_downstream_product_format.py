"""Observed product-format premises cannot hide inside downstream hypotheses."""
from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from app.module_execution.executors.common import (
    EvidenceSourceClass, ExecutorOutputError, OutputFailureStage, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.downstream_fidelity import selected_sources, validate_leaf
from app.module_registry import ModuleId
from tests.test_module_executors import fact
from tests.test_strategy_intelligence import run, valid_request


TRUTH = 'Участники выполняют практические задания и получают письменную обратную связь.'
DEMO = 'Демонстрационный образец показывает сравнение снимков.'
PERSONAL = 'Курс включает персональную письменную обратную связь.'
CONTENTS = 'Письменная обратная связь показывает конкретные изменения в снимках.'
CMO_BET = ('Аудитория отреагирует сильнее на сообщение о системной практике и персональном '
           'письменном отклике, чем на общие обещания обучения')
EXP_MECHANISM = ('Практические задания дают явный контекст для применения навыков, а письменная '
                 'обратная связь показывает конкретные изменения в снимках, что снижает '
                 'неопределённость клиента и даёт ориентир для следующей практики.')
POLICY = ('Рекомендация перед публикацией — проверить, не подменяет ли сообщение практические '
          'задания домашними, а письменную обратную связь персональным разбором; уточнить темы '
          'курса и темп освоения у владельца.')
EXISTING_CONTROL = ('Существующее нейтральное сообщение курса без явного акцента на письменной '
                    'обратной связи, описывающее курс как набор практических заданий и общей поддержки.')
APPROVED_TREATMENT = ('Вариант сообщения с явным операционным описанием формата; текст и лендинг '
                      'согласованы с владельцем, чтобы не заявлять неподтверждённые эффекты.')
STANDARDIZED = 'Курс включает стандартизированную письменную обратную связь.'
CMO_STANDARDIZED_RISK = ('Риск несоответствия: аудитория ожидает персонального разбора вместо '
                         'стандартизированной письменной обратной связи.')
CMO_STANDARDIZED_TRADEOFF = ('Риск переформулировать письменную обратную связь как индивидуальный '
                           'разбор вместо стандартизованной обратной связи.')


@pytest.mark.parametrize('text',[
    STANDARDIZED, CMO_STANDARDIZED_RISK,
    'Гипотеза: сообщение о стандартизированной письменной обратной связи привлечёт больше обращений.',
    'Письменная обратная связь является стандартизированной.',
    'Письменная обратная связь стандартизирована.',
    'Письменная обратная связь будет стандартизирована.',
    'Курс включает стандартизованную письменную обратную связь.',
    'Письменная обратная связь стандартизована.',
    'Письменная обратная связь будет стандартизована.',
    'Обратная связь будет индивидуальной.',
    'Our course includes standardized written feedback.',
    'Hypothesis: standardised feedback will increase interest in the course.',
    'The written feedback is standardized.',
])
def test_standardized_delivery_needs_whole_selected_owner_proof_even_in_risks_or_hypotheses(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text,owner=(TRUTH,),demo=(DEMO,))
    validate_leaf(text,owner=(text,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text,demo=(text,))


@pytest.mark.parametrize('kind',['HYPOTHESIS','RECOMMENDATION'])
def test_actual_cmo_risk_cannot_add_a_standardized_current_service(kind):
    def inject(payload,data):
        row=next(row for row in payload['outputs'] if row['output_name']=='risks')
        row.update(items=[CMO_STANDARDIZED_RISK],kind=kind)
    with pytest.raises(ExecutorOutputError) as caught:
        run(with_fact(ModuleId.VIRTUAL_CMO),inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize('kind',['HYPOTHESIS','RECOMMENDATION'])
def test_actual_cmo_tradeoff_cannot_presuppose_a_standardized_current_service(kind):
    def inject(payload,data):
        row=next(row for row in payload['outputs'] if row['output_name']=='trade_offs')
        row.update(items=[CMO_STANDARDIZED_TRADEOFF],kind=kind)
    with pytest.raises(ExecutorOutputError) as caught:
        run(with_fact(ModuleId.VIRTUAL_CMO),inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize('text',[
    'Проверить, предпочитает ли аудитория стандартизированную письменную обратную связь.',
    'Цель аудитории — получить стандартизированную обратную связь.',
    'Уточнить у владельца, включает ли курс стандартизированную обратную связь.',
    'Не обещать стандартизированную обратную связь без подтверждения владельца.',
    'Check whether customers prefer standardized written feedback.',
    'Audience goal: receive standardised feedback.',
    'Do not promise standardized feedback without owner confirmation.',
    'Рекомендуется стандартизировать форму обратной связи после согласования с владельцем.',
    'Propose standardizing the feedback process for owner approval before changing the service.',
])
def test_closed_standardized_preferences_and_future_operator_verbs_are_not_existing_delivery(text):
    validate_leaf(text)
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text+' '+STANDARDIZED)


@pytest.mark.parametrize('text', [
    EXISTING_CONTROL, APPROVED_TREATMENT, 'Текущий лендинг описывает курс.',
    'Использовать существующее контрольное сообщение.',
    'Existing neutral message describing general course support.',
    'Use the current landing page.', 'Text and landing page have been approved by the owner.',
    'The copy is approved by the owner.',
])
def test_copy_asset_and_completed_approval_claims_need_selected_whole_owner_truth(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, copy_field=True)
    validate_leaf(text, copy_field=True, owner=(text,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, copy_field=True, demo=(text,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text+' '+TRUTH, copy_field=True, owner=(TRUTH,))


@pytest.mark.parametrize('name,text', [('control',EXISTING_CONTROL),('treatment',APPROVED_TREATMENT)])
@pytest.mark.parametrize('kind',['HYPOTHESIS','RECOMMENDATION'])
def test_actual_executor_rejects_saved_existing_copy_and_approval_premises(name,text,kind):
    def inject(payload,data):
        row=next(row for row in payload['outputs'] if row['output_name']==name)
        row.update(text=text,kind=kind)
    with pytest.raises(ExecutorOutputError) as caught:
        run(valid_request(ModuleId.EXPERIMENTS),inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize('text',[
    'Подготовить новое нейтральное сообщение по подтверждённым сведениям владельца; согласовать до теста.',
    'Текст должен быть согласован с владельцем до запуска теста.',
    'Если существует нейтральное сообщение, проверить его у владельца перед использованием.',
    'Prepare a new control message using confirmed owner facts; obtain owner approval before testing.',
    'The copy must be approved by the owner before the test.',
    'If an existing message is available, confirm its content before using it.',
])
def test_proposed_copy_and_pending_owner_approval_are_not_completed_state_assertions(text):
    validate_leaf(text,copy_field=True)


@pytest.mark.parametrize('text', [
    'Собрать индивидуальные отзывы аудитории о сообщении.',
    'Получить персональные отклики представителей аудитории о тестовом сообщении.',
    'Collect personal feedback from the audience about the message.',
    'Gather individual reviews from the audience about the test message.',
    'Уточнить у владельца, включает ли курс персональную обратную связь.',
    'Confirm with the owner whether the course includes personal feedback.',
])
def test_explicit_audience_research_collection_is_not_owner_feedback_delivery(text):
    validate_leaf(text)
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + ' ' + PERSONAL)


@pytest.mark.parametrize('module,name', [
    (ModuleId.VIRTUAL_CMO, 'resource_priorities'), (ModuleId.EXPERIMENTS, 'learning_record.'),
])
def test_actual_executor_preserves_audience_research_collection_without_owner_format_proof(module, name):
    text = 'Собрать индивидуальные отзывы аудитории о сообщении.'
    def inject(payload, data):
        next(row for row in payload['outputs'] if row['output_name'] == name)['text'] = text
    result = run(valid_request(module), inject)
    assert any(row['output_name'] == name and row['text'] == text for row in result.payload['outputs'])


def with_fact(module, role='product_truth', value=TRUTH):
    req = valid_request(module)
    return replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact(role, value))))


@pytest.mark.parametrize('text', [
    CMO_BET, EXP_MECHANISM, PERSONAL, CONTENTS,
    'Добавить демонстрационный образец сравнения снимков, сопровождаемый пояснением, что это иллюстрация формата письменной обратной связи.',
    'The demonstration sample illustrates the written feedback format.',
    'The demonstration sample shows the feedback format.',
    'Гипотеза: ' + PERSONAL, 'Если это гипотеза, курс включает индивидуальный разбор.',
    'Copy: "Our course includes personalized written feedback".',
    'We offer individual reviews.', 'The feedback is personalized.',
    'Обратная связь является индивидуальной.',
    'Written feedback contains detailed corrections.',
    'Written feedback illustrates specific changes in photos.',
    'The written feedback that shows concrete improvements is part of the course.',
    'Письменная обратная связь, которая показывает конкретные изменения, включена в курс.',
    'Письменная обратная связь содержит подробные рекомендации.',
    'Гипотеза: письменная обратная связь может показывать изменения в снимках.',
    'Hypothesis: written feedback can show improvements in photos.',
    'Our course includes personal, written feedback.',
    'Our course provides individual and written reviews.',
    'Курс включает персональную и письменную обратную связь.',
    'Written feedback includes a detailed comparison of photos.',
])
def test_recognized_product_features_need_whole_owner_truth_even_as_hypotheses(text):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(TRUTH,), demo=(DEMO,))
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH


@pytest.mark.parametrize('module,text,output_name', [
    (ModuleId.VIRTUAL_CMO, CMO_BET, 'strategic_bets'),
    (ModuleId.EXPERIMENTS, EXP_MECHANISM, 'mechanism'),
])
def test_saved_live_cmo_and_experiment_product_premises_reject_before_result(module, text, output_name):
    req = with_fact(module)
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact('existing_proof', DEMO))))
    def inject(payload, data):
        row = next(row for row in payload['outputs'] if row['output_name'] == output_name)
        row['kind'] = 'HYPOTHESIS'
        if module is ModuleId.VIRTUAL_CMO:
            row['items'] = [text]
        else:
            row['text'] = text
        row['evidence_ids'] = [item['evidence_id'] for item in data['local_evidence']]
    with pytest.raises(ExecutorOutputError) as caught:
        run(req, inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_saved_nested_demo_intervention_cannot_claim_feedback_format_from_a_comparison():
    text = ('Добавить на лендинг демонстрационный образец сравнения снимков, '
            'сопровождаемый пояснением, что это иллюстрация формата письменной обратной связи.')
    def inject(payload, data):
        payload['experiments'][0]['intervention'] = text
    with pytest.raises(ExecutorOutputError) as caught:
        run(with_fact(ModuleId.EXPERIMENTS), inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize('text', [
    'В коммуникации избегать формулировок, которые можно понять как замену персонального разбора.',
    'Не приписывать конкурентам отсутствие обратной связи; в коммуникации избегать формулировок, которые можно понять как замену персонального разбора; держать описание формата обратной связи точным и согласованным с владельцем курса.',
    'Не обещать персональный разбор, пока формат обратной связи и объём не согласованы с владельцем; все публичные формулировки должны соответствовать подтверждённому описанию продукта.',
    'Не гарантировать индивидуальную обратную связь без подтверждения владельца.',
    'Не рекламировать персональный разбор.',
    'Do not promise personalized feedback without owner confirmation.',
    'Do not guarantee individual reviews.',
])
def test_closed_negative_format_mention_masks_only_that_mention(text):
    validate_leaf(text)
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + ' ' + PERSONAL)
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + ' Письменная обратная связь содержит конкретные изменения в снимках.')


@pytest.mark.parametrize('module,name', [
    (ModuleId.VIRTUAL_CMO, 'risks'), (ModuleId.EXPERIMENTS, 'guardrails'),
])
def test_actual_executor_preserves_negative_personal_promise_policy(module, name):
    text = ('Не обещать персональный разбор, пока формат обратной связи и объём не согласованы '
            'с владельцем; все публичные формулировки должны соответствовать подтверждённому описанию продукта.')
    def inject(payload, data):
        next(row for row in payload['outputs'] if row['output_name'] == name)['text'] = text
    result = run(valid_request(module), inject)
    assert any(row['output_name'] == name and row['text'] == text for row in result.payload['outputs'])


@pytest.mark.parametrize('text', [
    'Курс будет в коммуникации избегать формулировок, которые можно понять как замену персонального разбора.',
    'В коммуникации избегать формулировок, которые можно понять как замену персонального разбора, который включён в курс.',
    'В коммуникации избегать формулировок, которые можно понять как замену персонального разбора и письменной обратной связи, которую предлагает курс.',
    'Курс будет не обещать персональный разбор.',
    'Не обещать персональный разбор, который уже включён в курс.',
    'Не обещать персональный разбор, пока курс уже включает персональный разбор.',
    'Do not promise personal feedback which the course already includes.',
])
def test_negative_policy_prefix_does_not_mask_a_product_or_relative_assertion(text):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text)


@pytest.mark.parametrize('module,location', [
    (ModuleId.VIRTUAL_CMO, 'text'), (ModuleId.VIRTUAL_CMO, 'items'),
    (ModuleId.VIRTUAL_CMO, 'assumptions'), (ModuleId.VIRTUAL_CMO, 'limitations'),
    (ModuleId.EXPERIMENTS, 'text'), (ModuleId.EXPERIMENTS, 'hypothesis'),
    (ModuleId.EXPERIMENTS, 'intervention'), (ModuleId.EXPERIMENTS, 'expected_signal'),
    (ModuleId.EXPERIMENTS, 'minimum_required_inputs'),
    (ModuleId.EXPERIMENTS, 'assumptions'), (ModuleId.EXPERIMENTS, 'limitations'),
])
def test_format_premise_cannot_move_into_another_persisted_leaf(module, location):
    def inject(payload, data):
        if location == 'text':
            payload['outputs'][0]['text'] = CONTENTS
            payload['outputs'][0]['kind'] = 'HYPOTHESIS'
        elif location == 'items':
            payload['outputs'][0]['items'] = [CONTENTS]
        elif location in {'assumptions', 'limitations'}:
            payload[location] = [CONTENTS]
        else:
            payload['experiments'][0][location] = [CONTENTS] if location == 'minimum_required_inputs' else CONTENTS
    with pytest.raises(ExecutorOutputError) as caught:
        run(with_fact(module), inject)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize('text', [PERSONAL, CONTENTS, 'Our course includes individual written feedback.'])
def test_exact_whole_owner_source_is_allowed_without_turning_demo_into_owner(text):
    validate_leaf(text, owner=(text,))
    validate_leaf('Сообщение: «' + text + '»', owner=(text,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, demo=(text,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + ' ' + TRUTH, owner=(TRUTH,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + ' ' + TRUTH, owner=(text,))


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
@pytest.mark.parametrize('role,selected,allowed', [
    ('product_truth', True, True), ('confirmed_business_fact', True, True),
    ('product_truth', False, False), ('existing_proof', True, False),
    ('target_or_target_hypothesis', True, False),
])
def test_actual_owner_format_witness_is_typed_and_selected_per_output(module, role, selected, allowed):
    def inject(payload, data):
        row = next(row for row in payload['outputs']
                   if row['output_name'] == ('strategic_bets' if module is ModuleId.VIRTUAL_CMO else 'mechanism'))
        row['text'] = PERSONAL
        row['kind'] = 'HYPOTHESIS'
        identity = next(item['evidence_id'] for item in data['local_evidence'] if item['input_key'] == role)
        row['evidence_ids'] = [identity] if selected else []
    if allowed:
        assert run(with_fact(module, role, PERSONAL), inject).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError):
            run(with_fact(module, role, PERSONAL), inject)


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_actual_owner_role_cannot_be_borrowed_from_external_source_class(module, monkeypatch):
    from app.module_execution.executors import experiments, virtual_cmo
    implementation = virtual_cmo if module is ModuleId.VIRTUAL_CMO else experiments
    original = implementation.first_party_evidence
    def external(*args, **kwargs):
        return tuple(replace(item, record=replace(item.record, source_class=EvidenceSourceClass.EXTERNAL_PRIMARY))
                     if item.input_key == 'product_truth' else item
                     for item in original(*args, **kwargs))
    monkeypatch.setattr(implementation, 'first_party_evidence', external)
    def inject(payload, data):
        row = payload['outputs'][0]
        row['text'] = PERSONAL
        identity = next(item['evidence_id'] for item in data['local_evidence'] if item['input_key'] == 'product_truth')
        row['evidence_ids'] = [identity]
    with pytest.raises(ExecutorOutputError):
        run(with_fact(module, value=PERSONAL), inject)


@pytest.mark.parametrize('source_class', [EvidenceSourceClass.EXTERNAL_PRIMARY, EvidenceSourceClass.EXTERNAL_SECONDARY])
def test_local_owner_role_still_requires_first_party_class(source_class):
    source = SimpleNamespace(input_key='product_truth', value=PERSONAL,
             record=SimpleNamespace(source_class=source_class))
    owner, demo = selected_sources(SimpleNamespace(evidence_ids=['source']), {'source': source})
    assert not owner
    with pytest.raises(StatementSemanticsError):
        validate_leaf(PERSONAL, owner=owner, demo=demo)


@pytest.mark.parametrize('select_first', [False, True])
def test_nested_design_uses_only_first_claim_owner_selection(select_first):
    def inject(payload, data):
        identity = next(item['evidence_id'] for item in data['local_evidence'] if item['input_key'] == 'product_truth')
        for row in payload['outputs']:
            row['evidence_ids'] = []
        payload['outputs'][0 if select_first else 1]['evidence_ids'] = [identity]
        payload['experiments'][0]['intervention'] = PERSONAL
    req = with_fact(ModuleId.EXPERIMENTS, value=PERSONAL)
    if select_first:
        assert run(req, inject).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError):
            run(req, inject)


@pytest.mark.parametrize('text', [
    'Исследовать, важна ли аудитории персональная обратная связь.',
    'Проверить, предпочитает ли аудитория персональный письменный отклик.',
    'Нужна ли участникам индивидуальная обратная связь?',
    'Цель аудитории — получить персональную обратную связь.',
    'Гипотеза: аудитории важна персональная обратная связь.',
    'Ask whether customers value personalized feedback.',
    'Do participants prefer individual written feedback?',
    'Audience goal: receive personalized feedback.',
    'Audience preference hypothesis: customers value personal feedback.',
    'Проверить, помогает ли письменная обратная связь выбрать следующий шаг практики.',
    'Check whether written feedback helps the audience choose a next practice step.',
    POLICY,
    'Не приравнивать письменную обратную связь к персональному разбору без подтверждения владельца.',
    'Do not equate written feedback with personalized review without owner confirmation.',
    'Не обещать «Вы получите персональную обратную связь».',
    'Do not promise "you will receive personalized feedback".',
    'Ask whether customers want written feedback that shows concrete changes in photos.',
    'Audience goal: receive written feedback that shows concrete changes in photos.',
    'Проверить, нужна ли аудитории письменная обратная связь, которая показывает конкретные изменения в снимках.',
    'Цель аудитории — получить письменную обратную связь, которая показывает конкретные изменения в снимках.',
])
def test_closed_audience_research_goals_preferences_and_policy_are_not_existing_product_features(text):
    validate_leaf(text)


@pytest.mark.parametrize('module', [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_actual_executor_preserves_the_complete_server_warning_and_closed_research_question(module):
    def inject(payload, data):
        payload['outputs'][0]['text'] = POLICY
        payload['limitations'] = ['Ask whether customers value personalized feedback.']
    assert run(valid_request(module), inject).normalized_result.claims


@pytest.mark.parametrize('text', [
    'Ask whether customers value personalized feedback. Our course includes personal reviews.',
    'Audience goal: receive personalized feedback. The feedback shows concrete changes.',
    'Гипотеза: аудитории важна персональная обратная связь, которую предоставляет наш курс.',
    'Проверить, предпочитает ли аудитория персональный разбор; курс уже содержит его.',
    'Hypothesis: customers value individual feedback which our course provides.',
    POLICY + ' ' + PERSONAL,
    'Do not equate written feedback with personalized review without owner confirmation. ' + PERSONAL,
    'Не обещать «Вы получите персональную обратную связь». ' + CONTENTS,
    'Audience goal: receive written feedback that shows concrete changes in photos. ' + PERSONAL,
])
def test_closed_safe_prefix_cannot_launder_compound_existing_format_claim(text):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(TRUTH,), demo=(DEMO,))
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH


def test_foreign_attribution_is_not_owner_authority_for_our_personal_feedback():
    foreign = 'The competitor site states: Our course includes personalized feedback.'
    validate_leaf(foreign, comparisons=(foreign,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(PERSONAL, comparisons=(foreign,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(foreign + ' ' + PERSONAL, comparisons=(foreign,))


def test_saved_mu_equipment_qualifier_loss_requires_complete_owner_truth():
    qualified = TRUTH + ' Для занятий не требуется профессиональное оборудование.'
    text = ('Рабочая ставка — если аудитория ценит письменную обратную связь как ориентир, акцент на этом '
            'усилит релевантность и обращения; альтернативная ставка — акцент на практику и доступность '
            'без оборудования окажется более убедительным.')
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(qualified,))
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH


EQUIPMENT_TRUTH = TRUTH + ' Для занятий не требуется профессиональное оборудование.'
EQUIPMENT_SAFE = (
    'Проверить, предпочитает ли аудитория обучение без профессионального оборудования.',
    'Цель аудитории — заниматься без оборудования.',
    'Уточнить у владельца, возможно ли обучение без профессионального оборудования.',
    'Проверить, возможно ли обучение без оборудования.',
    'Исследовать интерес аудитории к обучению без профессионального оборудования.',
    'Проверить возможность обучения без оборудования и согласовать условия с владельцем до публикации.',
    'Не обещать обучение без оборудования без подтверждения владельца.',
    'Check whether customers prefer learning without professional equipment.',
    'Audience goal: learn without equipment.',
    'Audience goal: learn without any equipment.',
    'Check whether customers prefer learning without any professional gear.',
    'Confirm with the owner whether learning without professional gear is possible.',
    'Check whether learning without equipment is possible.',
    'Research audience interest in learning without professional equipment.',
    'Test whether learning without equipment is feasible before asking the owner to approve it.',
    'Do not promise learning without equipment without owner confirmation.',
)


@pytest.mark.parametrize('text', [
    'Без оборудования.', 'Обучение без профессионального оборудования доступно.',
    'Для занятий не требуется профессиональное оборудование.', 'Оборудование не требуется.',
    'Профессиональное оборудование не потребуется.', 'Не нужно покупать оборудование.',
    'Без необходимости приобретения оборудования.',
    'Акцент на доступности без оборудования снизит барьер.',
    'Hypothesis: the course is accessible without equipment.',
    'Learning without professional gear.', 'No equipment required.',
    'Professional equipment is not required.', 'No need to buy professional equipment.',
    'The course does not require equipment.', 'You do not need professional gear.',
])
def test_all_recognized_equipment_absence_needs_whole_selected_owner_source(text):
    from app.module_execution.executors.positioning_assurance import equipment_absence_spans
    assert equipment_absence_spans(text)
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(EQUIPMENT_TRUTH,), demo=(text,))
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH
    validate_leaf(text, owner=(text,))


def test_equipment_exact_qualified_and_independently_unqualified_sources_keep_their_own_scope():
    validate_leaf(EQUIPMENT_TRUTH, owner=(EQUIPMENT_TRUTH,))
    validate_leaf('«' + EQUIPMENT_TRUTH + '»', owner=(EQUIPMENT_TRUTH,))
    unqualified = 'Для занятий не требуется оборудование.'
    validate_leaf(unqualified, owner=(unqualified,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(unqualified, owner=(EQUIPMENT_TRUTH,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf('Для занятий не требуется профессиональное оборудование.', owner=(EQUIPMENT_TRUTH,))
    with pytest.raises(StatementSemanticsError):
        validate_leaf(EQUIPMENT_TRUTH + ' ' + unqualified, owner=(EQUIPMENT_TRUTH, unqualified))


@pytest.mark.parametrize('text', EQUIPMENT_SAFE)
def test_equipment_closed_questions_goals_and_future_plans_do_not_assert_current_conditions(text):
    validate_leaf(text)
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text, copy_field=True)
    with pytest.raises(StatementSemanticsError):
        validate_leaf('«' + text + '»')


@pytest.mark.parametrize('text', EQUIPMENT_SAFE)
@pytest.mark.parametrize('suffix', [
    ' Курс доступен без оборудования.', ' Курс включает персональный разбор.',
    ' The course requires no equipment.', ' The feedback shows concrete changes.',
    ' Text and landing page have been approved by the owner.',
    ' You will learn without equipment.',
])
def test_equipment_safe_whole_leaf_cannot_launder_appended_claims(text, suffix):
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text + suffix, owner=(EQUIPMENT_TRUTH,))


@pytest.mark.parametrize('text', [
    'Проверить, почему курс доступен без оборудования.',
    'Проверить, насколько доступен курс без профессионального оборудования.',
    'Проверить интерес к курсу, который не требует оборудования.',
    'Hypothesis: students value learning without equipment which our course provides.',
    'Check how the course works without equipment.',
    'Audience goal: learn without equipment; our course meets that goal.',
    'Уточнить у владельца, возможно ли обучение без оборудования, которое уже доступно.',
])
def test_equipment_question_or_hypothesis_prefix_does_not_hide_presupposition(text):
    # Some synonyms remain outside the deliberately finite detector; these
    # concrete cases contain recognized absence phrases and must not be waived.
    with pytest.raises(StatementSemanticsError):
        validate_leaf(text)


@pytest.mark.parametrize('module,name', [(ModuleId.VIRTUAL_CMO, 'strategic_bets'),
                                         (ModuleId.EXPERIMENTS, 'mechanism')])
@pytest.mark.parametrize('kind', ['HYPOTHESIS', 'RECOMMENDATION'])
@pytest.mark.parametrize('source', ['selected', 'unselected', 'demo', 'hyp_parent'])
def test_normal_downstream_equipment_source_boundary(module, name, kind, source):
    req = valid_request(module)
    if source == 'hyp_parent':
        from app.marketing_orchestrator.quality_gates.contracts import ClaimType
        from app.orchestration_runtime.serialization import result_to_json
        from tests.test_strategy_intelligence import positioning, upstream
        parent = positioning()
        parent = replace(parent, payload=result_to_json(parent)['payload'],
            normalized_result=replace(parent.normalized_result, claims=tuple(
                replace(claim, value=EQUIPMENT_TRUTH, claim_type=ClaimType.HYPOTHESIS)
                for claim in parent.normalized_result.claims)))
        req = replace(req, upstream_results=upstream(parent))
    else:
        role = 'existing_proof' if source == 'demo' else 'confirmed_business_fact'
        req = replace(req, context_packet=replace(req.context_packet,
            known_facts=(*req.context_packet.known_facts, fact(role, EQUIPMENT_TRUTH))))
    def inject(payload, data):
        row = next(row for row in payload['outputs'] if row['output_name'] == name)
        row.update(text=EQUIPMENT_TRUTH, kind=kind)
        if source in {'selected', 'demo'}:
            row['evidence_ids'] = [item['evidence_id'] for item in data['local_evidence'] if item['input_key'] == role]
        else:
            row['evidence_ids'] = []
    if source == 'selected':
        result = run(req, inject)
        assert next(row for row in result.payload['outputs'] if row['output_name'] == name)['text'] == EQUIPMENT_TRUTH
        from app.module_execution.acceptance import fully_accepted
        from app.orchestration_runtime.service import evaluate_result
        quality = evaluate_result(hashlib.sha256(req.execution_id.encode()).hexdigest()[:32], result, req.upstream_results)
        assert fully_accepted(result, quality['accepted_result_ids'], quality['accepted_claim_ids'])
    else:
        with pytest.raises(ExecutorOutputError) as caught:
            run(req, inject)
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_equipment_detection_does_not_change_positioning_assurance_or_truth_authority():
    from app.module_execution.executors.positioning_assurance import (
        equipment_absence_spans, has_product_assurance, supports_no_equipment_purchase,
    )
    assert equipment_absence_spans('Обучение без профессионального оборудования.')
    assert not has_product_assurance('Обучение без профессионального оборудования.')
    assert has_product_assurance('Курс без профессионального оборудования ведёт профессиональный преподаватель.')
    assert supports_no_equipment_purchase(EQUIPMENT_TRUTH)
    assert not supports_no_equipment_purchase('Для занятий не требуется оборудование.')
    assert not supports_no_equipment_purchase('Обучение без профессионального оборудования доступно.')


@pytest.mark.parametrize('text', [
    'The course requires no equipment.',
    'Learning without any equipment.',
    'The classes require no equipment.',
    'The course requires no professional equipment.',
    'Learning without any professional gear.',
    'There is no need to buy any equipment.',
    'You do not need any professional equipment.',
    'The course does not require any equipment.',
    "Students don't need any equipment.",
])
def test_english_equipment_absence_standalone_cannot_drop_owner_qualifier(text):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text, owner=(EQUIPMENT_TRUTH,))
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH
    validate_leaf(text, owner=(text,))
