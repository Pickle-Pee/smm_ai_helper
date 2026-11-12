"""Generation-only format filtering and explicit whole-owner quotation escape."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import EvidenceSourceClass, ExecutorOutputError, first_party_evidence, scoped_facts
from app.module_execution.executors.cmo_generation_policy import (
    CMO_GENERATION_PATTERN, FORMAT_WORDS, FORMAT_PREFIXES, contains_format_word,
    owner_quote_catalog, validate_owner_catalog, generation_field,
)
from app.module_execution.executors.cmo_support_wire import support_selection_wire_schema, support_selection_catalog, decode_support_selection_wire
from app.module_execution.executors.qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from app.module_execution.executors.regular_word_generation import allowed_word_pattern
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from tests.test_cmo_support_wire import scoped_request, contracts, wire_output
from tests.test_module_executors import fact

PATTERN = re.compile(CMO_GENERATION_PATTERN)
OWNER_QUOTE = "Курс включает индивидуальный разбор"
SAVED_FAILURE = "Риск переформулировать письменную обратную связь как индивидуальный разбор вместо стандартизованной обратной связи."


def test_frozen_generation_pattern_exact_utf8_hash_and_nonempty_generic_words():
    assert len(QUALITATIVE_GENERATION_PATTERN) == 959
    assert hashlib.sha256(QUALITATIVE_GENERATION_PATTERN.encode()).hexdigest() == "8cfe49afdb10b8f2319c466edc169619c93b7bb5a01aa4f0a88400cab042103c"
    empty = re.compile(allowed_word_pattern(()))
    assert not empty.fullmatch("")
    assert empty.fullmatch("word")


@pytest.mark.parametrize("word", sorted(FORMAT_WORDS) + [
    "персональная", "персональной", "индивидуальным", "стандартизованная",
    "стандартизована", "стандартизован", "стандартизированы", "стандартизированная",
])
def test_descriptor_families_case_multiline_and_maximal_token_boundaries(word):
    for form in (word, word.upper(), word.title()):
        assert contains_format_word(form)
        assert not PATTERN.fullmatch("Проверить\n" + form + " формат.")
    assert PATTERN.fullmatch("prefix" + word + ".")


@pytest.mark.parametrize("text", [SAVED_FAILURE, "Проверить два варианта.", "Compare two options.", "Text 2."])
def test_observed_format_and_existing_count_failures_reject(text):
    assert not PATTERN.fullmatch(text)


@pytest.mark.parametrize("text", [
    "Проверить интерес к письменной обратной связи.", "Согласовать формат с владельцем!",
    "Сравнить реакции на практику и обратную связь\n", "стандартизовать описание.",
    "personalities differ.", "individuality matters.", "twofold comparison.",
])
def test_case_specific_qualitative_prose_remains_open(text):
    assert PATTERN.fullmatch(text)


def test_one_trie_regular_outer_anchors_and_generation_only_terminal_separator():
    assert len(CMO_GENERATION_PATTERN) < 5000
    assert CMO_GENERATION_PATTERN.count("$") == 1
    assert re.sub(r"\[\^", "[", CMO_GENERATION_PATTERN).count("^") == 1
    for forbidden in ("(?=", "(?!", "(?<=", "(?<!", "(?i", r"\b", r"\w", r"\d"):
        assert forbidden not in CMO_GENERATION_PATTERN
    assert not PATTERN.fullmatch("ordinary word")
    assert PATTERN.fullmatch("ordinary word.")
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, "ordinary word")
    for text in (("Проверить реакцию. " * 250)[:3999] + ".", "." * 4000, "a" * 3999 + "."):
        assert PATTERN.fullmatch(text)
        assert not PATTERN.fullmatch(text[:-1] + "2")


def evidence(identity="evd_owner", text=OWNER_QUOTE, key="product_truth", source=EvidenceSourceClass.FIRST_PARTY):
    return SimpleNamespace(record=SimpleNamespace(evidence_id=identity, source_class=source), input_key=key, value=text)


def test_catalog_generator_complete_typed_owner_only_and_no_ordinary_numeric_escape():
    foreign = next(value for value in EvidenceSourceClass if value is not EvidenceSourceClass.FIRST_PARTY)
    rows = [evidence(), evidence("evd_confirmed", key="confirmed_business_fact"),
            evidence("evd_demo", key="existing_proof"), evidence("evd_audience", key="target_audience"),
            evidence("evd_foreign", source=foreign), evidence("evd_numeric", text="Курс включает два варианта индивидуального разбора."),
            evidence("evd_plain", text="Written feedback."), evidence("evd_structured", text={"text": OWNER_QUOTE}),
            evidence("evd_long", text="индивидуальный " + "x" * 4000)]
    assert owner_quote_catalog(iter(rows)) == [
        {"support_id": "evd_confirmed", "exact_quote": OWNER_QUOTE},
        {"support_id": "evd_owner", "exact_quote": OWNER_QUOTE}]


@pytest.mark.parametrize("catalog", [
    [{"support_id": "unknown", "exact_quote": OWNER_QUOTE}],
    [{"support_id": "evd_owner", "exact_quote": "Ordinary owner text."}],
    [{"support_id": "evd_owner", "exact_quote": "Personal feedback for two versions."}],
    [{"support_id": "evd_owner", "exact_quote": OWNER_QUOTE, "extra": True}],
    [{"support_id": "evd_owner", "exact_quote": OWNER_QUOTE}] * 2,
])
def test_catalog_unknown_shapes_ids_numerics_ordinary_and_duplicates_fail_closed(catalog):
    with pytest.raises(ModuleExecutionContractError):
        validate_owner_catalog(catalog, {"evd_owner"})


@pytest.mark.parametrize("rows", [
    [evidence(f"evd_{i}") for i in range(65)],
    [evidence(f"evd_{i}", text=OWNER_QUOTE + "x" * 3900) for i in range(5)],
])
def test_catalog_overflow_is_rejected_without_truncation(rows):
    with pytest.raises(ModuleExecutionContractError):
        owner_quote_catalog(rows)


def owner_request(outputs=None, quote=OWNER_QUOTE):
    req = scoped_request(outputs=outputs)
    return replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact("confirmed_business_fact", quote))))


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("field", ["text", "items"])
def test_normal_executor_requires_explicit_selected_owner_for_whole_quote(selected, field):
    req = owner_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        aliases = data["support_selection_catalog"]
        payload = wire_output(req.expected_outputs, aliases)
        statement = payload["outputs"]["trade_offs"]
        statement[field] = OWNER_QUOTE if field == "text" else [OWNER_QUOTE]
        identity = next(row["evidence_id"] for row in data["local_evidence"] if row["input_key"] == "confirmed_business_fact")
        alias = next(alias for alias, value in aliases["evidence"].items() if value == identity)
        statement["additional_evidence_support"][alias] = selected
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    if selected:
        result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
        statement = next(row for row in result.payload["outputs"] if row["output_name"] == "trade_offs")
        assert statement[field] == (OWNER_QUOTE if field == "text" else (OWNER_QUOTE,))
        assert statement["evidence_ids"]
    else:
        with pytest.raises(ExecutorOutputError):
            asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))


@pytest.mark.parametrize("field", ["text", "items"])
def test_all_free_outputs_and_globals_reject_saved_failure_and_preserve_bounds(field):
    req = owner_request()
    canonical, _, ids, parents, numeric = contracts(req)
    owner = owner_quote_catalog(first_party_evidence(req, scoped_facts(req)))
    schema = support_selection_wire_schema(canonical, req.expected_outputs, ids, parents, numeric, owner)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    assert Draft202012Validator(schema).is_valid(payload)
    for name in req.expected_outputs:
        if name == "risks":
            continue
        value = deepcopy(payload)
        value["outputs"][name][field] = SAVED_FAILURE if field == "text" else [SAVED_FAILURE]
        assert not Draft202012Validator(schema).is_valid(value)
    for global_field in ("assumptions", "limitations"):
        value = deepcopy(payload)
        value[global_field] = [OWNER_QUOTE]
        assert not Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize("quote", ["Prefix " + OWNER_QUOTE, OWNER_QUOTE + ". Appended claim.", OWNER_QUOTE[:20]])
def test_owner_enum_does_not_allow_paraphrase_prefix_suffix_or_fragments(quote):
    req = owner_request()
    canonical, _, ids, parents, numeric = contracts(req)
    owner = owner_quote_catalog(first_party_evidence(req, scoped_facts(req)))
    schema = support_selection_wire_schema(canonical, req.expected_outputs, ids, parents, numeric, owner)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    payload["outputs"]["trade_offs"]["text"] = quote
    assert not Draft202012Validator(schema).is_valid(payload)


def test_partial_request_owner_quote_bounds_and_unknown_schema_fail_closed():
    req = owner_request(outputs=("trade_offs",))
    canonical, _, ids, parents, numeric = contracts(req)
    owner = owner_quote_catalog(first_party_evidence(req, scoped_facts(req)))
    schema = support_selection_wire_schema(canonical, req.expected_outputs, ids, parents, numeric, owner)
    assert list(schema["properties"]["outputs"]["properties"]) == ["trade_offs"]
    field = {"type": "string", "minLength": 1, "maxLength": 300}
    assert generation_field(field, 300, [{"exact_quote": "personal " + "x" * 300}]).get("anyOf") is None
    with pytest.raises(ModuleExecutionContractError):
        generation_field({**field, "unknown": True}, 300, [])


@pytest.mark.parametrize("quoted_prose", [False, True])
def test_normal_executor_numeric_owner_value_stays_context_only(quoted_prose):
    quote = "Курс включает два варианта индивидуального разбора."
    req = owner_request(quote=quote)
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"])
        identity = next(row["evidence_id"] for row in data["local_evidence"] if row["input_key"] == "confirmed_business_fact")
        statement = payload["outputs"]["trade_offs"]
        if quoted_prose:
            statement["text"] = quote
        else:
            statement["numeric_context"] = [{"support_id": identity, "quote": quote}]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload) is not quoted_prose
        return json.dumps(payload)
    if quoted_prose:
        with pytest.raises(ExecutorOutputError):
            asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    else:
        result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
        statement = next(row for row in result.payload["outputs"] if row["output_name"] == "trade_offs")
        assert statement["numeric_context"][0]["quote"] == quote


def test_owner_enum_cannot_infer_citation_or_mutate_flags_and_duplicate_ids_stay_rejected():
    req = owner_request(outputs=("trade_offs",))
    canonical, _, ids, parents, numeric = contracts(req)
    owner = owner_quote_catalog(first_party_evidence(req, scoped_facts(req)))
    aliases = support_selection_catalog(ids, parents)
    payload = wire_output(req.expected_outputs, aliases)
    payload["outputs"]["trade_offs"]["text"] = OWNER_QUOTE
    before = deepcopy(payload)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, numeric, owner)

    assert payload == before
    identity = owner[0]["support_id"]
    alias = next(alias for alias, value in aliases["evidence"].items() if value == identity)
    payload["outputs"]["trade_offs"]["additional_evidence_support"][alias] = True
    before = deepcopy(payload)
    decoded = decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, numeric, owner)
    assert payload == before
    assert identity in decoded["outputs"][0]["evidence_ids"]
    payload["outputs"]["trade_offs"]["evidence_ids"] = [identity, identity]
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, numeric, owner)


def test_executor_schema_and_decode_preserve_owner_scope_with_generator_evidence():
    req = owner_request(outputs=("trade_offs",))
    canonical, _, ids, parents, _ = contracts(req)
    local = first_party_evidence(req, scoped_facts(req))
    executor = VirtualCMOExecutor(model_call=None, support_selection_wire=True)
    assert executor.wire_schema_for(req, canonical, iter(local)) == executor.wire_schema_for(req, canonical, local)
    aliases = support_selection_catalog(ids, parents)
    payload = wire_output(req.expected_outputs, aliases)
    statement = payload["outputs"]["trade_offs"]
    statement["text"] = OWNER_QUOTE
    identity = owner_quote_catalog(local)[0]["support_id"]
    alias = next(alias for alias, value in aliases["evidence"].items() if value == identity)
    statement["additional_evidence_support"][alias] = True
    assert executor.decode_wire_payload(req, payload, iter(local)) == executor.decode_wire_payload(req, payload, local)
