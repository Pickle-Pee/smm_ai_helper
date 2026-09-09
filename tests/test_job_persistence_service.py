from __future__ import annotations

import asyncio
import inspect
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

import app.services.job_persistence_service as job_service
from app.models import Job, JobStatus, MarketingRun, User
from app.services.job_persistence_service import (
    DirtyJobMutationError,
    IllegalJobTransitionError,
    InvalidJobDataError,
    InvalidJobJsonError,
    JobJsonTooLargeError,
    JobNotFoundError,
    JobPersistenceError,
    JobPersistenceService,
    JobVersionExhaustedError,
    MAX_JOB_VERSION,
    StaleJobVersionError,
)


JOB_ID = "0123456789abcdef0123456789abcdef"
OTHER_JOB_ID = "fedcba9876543210fedcba9876543210"
CREATED = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
STARTED = CREATED + timedelta(minutes=1)
COMPLETED = STARTED + timedelta(minutes=1)


class ScalarCollection:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class ExecuteResult:
    def __init__(self, *, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return ScalarCollection(self._scalars)


class FakeSession:
    def __init__(self, execute_results=(), *, flush_error=None):
        self.execute_results = list(execute_results)
        self.flush_error = flush_error
        self.executed = []
        self.added = []
        self.flush_arguments = []
        self.identity_map = {}
        self.deleted = set()
        self.no_autoflush_entries = 0

    @property
    def no_autoflush(self):
        self.no_autoflush_entries += 1
        return nullcontext()

    async def execute(self, statement):
        self.executed.append(statement)
        if not self.execute_results:
            raise AssertionError("unexpected execute")
        return self.execute_results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self, objects=None):
        self.flush_arguments.append(objects)
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self):
        raise AssertionError("service must not commit")

    def rollback(self):
        raise AssertionError("service must not roll back")

    def refresh(self, _value):
        raise AssertionError("service must not refresh")


class CountingClock:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if not self.values:
            raise AssertionError("unexpected clock call")
        return self.values.pop(0)


def run(coro):
    return asyncio.run(coro)


def make_job(
    status=JobStatus.PENDING,
    *,
    version=0,
    job_id=JOB_ID,
    payload_json=None,
):
    values = {
        "job_id": job_id,
        "kind": "competitor.analysis",
        "status": status,
        "version": version,
        "payload_json": {"seed": True} if payload_json is None else payload_json,
        "created_at": CREATED,
        "updated_at": CREATED,
        "started_at": None,
        "completed_at": None,
        "result_json": None,
        "error": None,
    }
    if status is JobStatus.RUNNING:
        values.update(updated_at=STARTED, started_at=STARTED)
    elif status is JobStatus.SUCCEEDED:
        values.update(
            updated_at=COMPLETED,
            started_at=STARTED,
            completed_at=COMPLETED,
            result_json={"ok": True},
        )
    elif status is JobStatus.FAILED:
        values.update(
            updated_at=COMPLETED,
            started_at=STARTED,
            completed_at=COMPLETED,
            error="sanitized failure",
        )
    return Job(**values)


def assert_no_write(session):
    assert session.added == []
    assert session.flush_arguments == []


def test_error_taxonomy_is_exact_and_safe():
    classes = (
        JobPersistenceError,
        InvalidJobDataError,
        InvalidJobJsonError,
        JobJsonTooLargeError,
        DirtyJobMutationError,
        JobNotFoundError,
        StaleJobVersionError,
        JobVersionExhaustedError,
        IllegalJobTransitionError,
    )
    assert len(classes) == 9
    assert len(set(classes)) == 9
    assert issubclass(InvalidJobJsonError, InvalidJobDataError)
    assert issubclass(JobJsonTooLargeError, InvalidJobDataError)
    assert all(issubclass(error, JobPersistenceError) for error in classes[1:])


def test_public_method_signatures_expose_no_generic_mutation_or_caller_version():
    create_parameters = inspect.signature(
        JobPersistenceService.create_job
    ).parameters
    transition_parameters = inspect.signature(
        JobPersistenceService.transition_job
    ).parameters
    assert tuple(create_parameters) == (
        "self",
        "db_session",
        "kind",
        "payload_json",
        "user_id",
        "marketing_run_id",
        "workflow_step",
        "job_id",
    )
    assert "version" not in create_parameters
    assert "created_at" not in create_parameters
    assert transition_parameters["expected_version"].default is inspect.Parameter.empty
    assert transition_parameters["expected_version"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert set(name for name in dir(JobPersistenceService) if not name.startswith("_")) == {
        "create_job",
        "get_job",
        "list_jobs_for_run",
        "transition_job",
    }


def test_create_system_job_uses_one_clock_copy_and_one_scoped_flush():
    offset = timezone(timedelta(hours=3))
    supplied_time = datetime(2026, 8, 25, 11, 2, 3, 456789, tzinfo=offset)
    clock = CountingClock(supplied_time)
    session = FakeSession()
    original = {"nested": {"value": 1}}

    job = run(
        JobPersistenceService(clock).create_job(
            session,
            kind="competitor.analysis",
            payload_json=original,
            job_id=JOB_ID,
        )
    )
    original["nested"]["value"] = 99

    assert job.job_id == JOB_ID
    assert job.user_id is None and job.marketing_run_id is None
    assert job.workflow_step is None
    assert job.status is JobStatus.PENDING and job.version == 0
    assert job.payload_json == {"nested": {"value": 1}}
    assert job.created_at == supplied_time.astimezone(timezone.utc)
    assert job.updated_at == job.created_at
    assert job.started_at is job.completed_at is job.result_json is job.error is None
    assert clock.calls == 1
    assert session.added == [job]
    assert session.flush_arguments == [[job]]


def test_create_with_none_payload_gets_independent_empty_objects():
    clock = CountingClock(CREATED, CREATED)
    session = FakeSession()
    service = JobPersistenceService(clock)

    first = run(service.create_job(session, kind="a", job_id=JOB_ID))
    second = run(service.create_job(session, kind="a", job_id=OTHER_JOB_ID))

    assert first.payload_json == second.payload_json == {}
    assert first.payload_json is not second.payload_json


def test_generated_job_id_is_lowercase_uuid_hex():
    sync_session, facade = make_identity_session()
    try:
        job = run(
            JobPersistenceService(lambda: CREATED).create_job(
                facade, kind="valid"
            )
        )
        assert len(job.job_id) == 32
        assert set(job.job_id) <= set("0123456789abcdef")
    finally:
        sync_session.close()


def test_duplicate_job_id_database_error_propagates_for_caller_rollback():
    sync_session, facade = make_identity_session()
    try:
        first = run(
            JobPersistenceService(lambda: CREATED).create_job(
                facade, kind="valid", job_id=JOB_ID
            )
        )
        sync_session.commit()
        sync_session.expunge(first)
        with pytest.raises(IntegrityError):
            run(
                JobPersistenceService(lambda: CREATED).create_job(
                    facade, kind="valid", job_id=JOB_ID
                )
            )
        assert sync_session.is_active is False
    finally:
        sync_session.rollback()
        sync_session.close()


def test_create_run_owner_queries_before_clock_and_supports_step():
    owner = MarketingRun(run_id="run-1", workflow_type="mvp")
    clock = CountingClock(CREATED)
    session = FakeSession([ExecuteResult(scalar=owner)])

    job = run(
        JobPersistenceService(clock).create_job(
            session,
            kind="creative.package",
            marketing_run_id="run-1",
            workflow_step="creative.package",
        )
    )

    assert job.marketing_run_id == "run-1" and job.user_id is None
    assert job.workflow_step == "creative.package"
    assert len(session.executed) == 1 and clock.calls == 1
    assert "marketing_runs.run_id" in str(session.executed[0])


def test_create_direct_user_owner_queries_and_prohibits_step():
    owner = User(id=7, telegram_id=70)
    clock = CountingClock(CREATED)
    session = FakeSession([ExecuteResult(scalar=owner)])

    job = run(
        JobPersistenceService(clock).create_job(
            session,
            kind="mentor.explanation",
            user_id=7,
        )
    )
    assert job.user_id == 7 and job.marketing_run_id is None
    assert "users.id" in str(session.executed[0])

    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(),
                kind="mentor.explanation",
                user_id=7,
                workflow_step="mentor.explanation",
            )
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"user_id": 1, "marketing_run_id": "run-1"},
        {"marketing_run_id": None, "workflow_step": "step"},
        {"user_id": True},
        {"user_id": 0},
        {"marketing_run_id": ""},
        {"marketing_run_id": "x" * 65},
        {"marketing_run_id": "x\x00"},
    ],
)
def test_creation_owner_shape_validation_precedes_session_access(kwargs):
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", **kwargs
            )
        )


def test_missing_owner_precedes_clock_and_add():
    clock = CountingClock()
    session = FakeSession([ExecuteResult(scalar=None)])
    with pytest.raises(InvalidJobDataError, match="owner does not exist"):
        run(
            JobPersistenceService(clock).create_job(
                session, kind="valid", user_id=7
            )
        )
    assert clock.calls == 0
    assert_no_write(session)


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", ""),
        ("job_id", "A" * 32),
        ("job_id", "g" * 32),
        ("job_id", 1),
        ("kind", ""),
        ("kind", "Upper"),
        ("kind", "two words"),
        ("kind", "a" * 65),
        ("workflow_step", "_bad"),
    ],
)
def test_identifier_and_canonical_key_rejection_precedes_session(field, value):
    kwargs = {"kind": "valid", "job_id": JOB_ID}
    kwargs[field] = value
    if field == "workflow_step":
        kwargs["marketing_run_id"] = "run"
    with pytest.raises(InvalidJobDataError):
        run(JobPersistenceService(lambda: CREATED).create_job(object(), **kwargs))


def test_exact_builtin_string_subclasses_are_rejected():
    class StringSubclass(str):
        pass

    for kwargs in (
        {"kind": StringSubclass("valid")},
        {"kind": "valid", "job_id": StringSubclass(JOB_ID)},
        {"kind": "valid", "marketing_run_id": StringSubclass("run")},
    ):
        with pytest.raises(InvalidJobDataError):
            run(JobPersistenceService(lambda: CREATED).create_job(object(), **kwargs))


def test_canonical_key_boundary_lengths_are_accepted_without_normalization():
    for kind in ("a", "a" + "0" * 63):
        job = run(
            JobPersistenceService(lambda: CREATED).create_job(
                FakeSession(), kind=kind
            )
        )
        assert job.kind == kind
    step = "s" + "0" * 63
    session = FakeSession([ExecuteResult(scalar=MarketingRun(run_id="r", workflow_type="mvp"))])
    job = run(
        JobPersistenceService(lambda: CREATED).create_job(
            session,
            kind="a",
            marketing_run_id="r",
            workflow_step=step,
        )
    )
    assert job.workflow_step == step


@pytest.mark.parametrize(
    "clock_value",
    [
        datetime(2026, 8, 25),
        "2026-08-25T00:00:00Z",
    ],
)
def test_invalid_clock_values_reject_before_add_or_flush(clock_value):
    session = FakeSession()
    with pytest.raises(InvalidJobDataError):
        run(JobPersistenceService(lambda: clock_value).create_job(session, kind="valid"))
    assert_no_write(session)


def test_datetime_subclass_clock_is_rejected():
    class DatetimeSubclass(datetime):
        pass

    session = FakeSession()
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService(
                lambda: DatetimeSubclass(2026, 8, 25, tzinfo=timezone.utc)
            ).create_job(session, kind="valid")
        )
    assert_no_write(session)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        (),
        {"value": (1, 2)},
        {"value": {1, 2}},
        {"value": b"bytes"},
        {"value": object()},
        {1: "non-string key"},
        {"value": 2**63},
        {"value": -(2**63) - 1},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": float("-inf")},
    ],
)
def test_json_domain_rejects_unsupported_values_before_session(payload):
    with pytest.raises(InvalidJobJsonError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", payload_json=payload
            )
        )


def test_json_rejects_subclasses_but_accepts_exact_scalar_boundaries():
    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    class IntSubclass(int):
        pass

    class StringSubclass(str):
        pass

    invalid = (
        DictSubclass(),
        {"v": ListSubclass()},
        {"v": IntSubclass(1)},
        {"v": StringSubclass("x")},
    )
    for payload in invalid:
        with pytest.raises(InvalidJobJsonError):
            run(
                JobPersistenceService(lambda: CREATED).create_job(
                    object(), kind="valid", payload_json=payload
                )
            )

    payload = {
        "none": None,
        "false": False,
        "true": True,
        "minimum": -(2**63),
        "maximum": 2**63 - 1,
        "float": 1.25,
        "string": "valid",
        "array": [],
        "object": {},
    }
    job = run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=payload
        )
    )
    assert job.payload_json == payload


def test_json_keys_and_result_top_level_require_exact_builtin_types():
    class StringSubclass(str):
        pass

    with pytest.raises(InvalidJobJsonError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(),
                kind="valid",
                payload_json={StringSubclass("key"): "value"},
            )
        )
    with pytest.raises(InvalidJobJsonError):
        run(
            JobPersistenceService().transition_job(
                object(),
                JOB_ID,
                1,
                JobStatus.SUCCEEDED,
                result_json=[],
            )
        )


def test_json_cycles_reject_and_repeated_acyclic_references_are_copied():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(InvalidJobJsonError, match="cycle"):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", payload_json=cyclic
            )
        )

    shared = {"value": 1}
    source = {"left": shared, "right": shared}
    job = run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=source
        )
    )
    assert job.payload_json == source
    assert job.payload_json is not source


def nested_payload(depth):
    value = "leaf"
    for _ in range(depth - 1):
        value = [value]
    return {"value": value}


def test_json_depth_16_accepts_and_depth_17_rejects():
    run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=nested_payload(16)
        )
    )
    with pytest.raises(InvalidJobJsonError, match="depth"):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", payload_json=nested_payload(17)
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"value": "contains\x00nul"},
        {"contains\x00nul": "value"},
        {"value": "\ud800"},
        {"\ud800": "value"},
    ],
)
def test_json_rejects_postgresql_incompatible_unicode(payload):
    with pytest.raises(InvalidJobJsonError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", payload_json=payload
            )
        )


def test_json_accepts_valid_unicode_and_measures_utf8_canonically():
    payload = {"кириллица": "🙂", "a": "é"}
    job = run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=payload
        )
    )
    assert job.payload_json == payload


def test_canonical_measurement_uses_the_exact_serialization_options(monkeypatch):
    calls = []
    real_dumps = job_service.json.dumps

    def recording_dumps(value, **kwargs):
        calls.append((value, kwargs))
        return real_dumps(value, **kwargs)

    monkeypatch.setattr(job_service.json, "dumps", recording_dumps)
    payload = {"z": "é", "a": 1}
    run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=payload
        )
    )
    assert calls == [
        (
            payload,
            {
                "ensure_ascii": False,
                "sort_keys": True,
                "separators": (",", ":"),
                "allow_nan": False,
            },
        )
    ]


def test_payload_byte_limit_accepts_exact_and_rejects_one_over():
    # Canonical form is exactly {"x":"<value>"}, with eight structural bytes.
    accepted = {"x": "a" * (262_144 - 8)}
    rejected = {"x": "a" * (262_144 - 7)}
    run(
        JobPersistenceService(lambda: CREATED).create_job(
            FakeSession(), kind="valid", payload_json=accepted
        )
    )
    with pytest.raises(JobJsonTooLargeError):
        run(
            JobPersistenceService(lambda: CREATED).create_job(
                object(), kind="valid", payload_json=rejected
            )
        )


def test_result_byte_limit_and_defensive_copy():
    accepted = {"x": "a" * (1_048_576 - 8)}
    rejected = {"x": "a" * (1_048_576 - 7)}
    running = make_job(JobStatus.RUNNING, version=1)
    session = FakeSession([ExecuteResult(scalar=running)])
    result = run(
        JobPersistenceService(lambda: COMPLETED).transition_job(
            session, JOB_ID, 1, JobStatus.SUCCEEDED, result_json=accepted
        )
    )
    accepted["x"] = "changed"
    assert len(result.result_json["x"]) == 1_048_576 - 8

    with pytest.raises(JobJsonTooLargeError):
        run(
            JobPersistenceService(lambda: COMPLETED).transition_job(
                object(), JOB_ID, 1, JobStatus.SUCCEEDED, result_json=rejected
            )
        )


def test_get_job_validates_then_queries_without_lock_or_flush():
    with pytest.raises(InvalidJobDataError):
        run(JobPersistenceService().get_job(object(), "bad"))

    job = make_job()
    existing_session = FakeSession([ExecuteResult(scalar=job)])
    missing_session = FakeSession([ExecuteResult(scalar=None)])
    assert run(JobPersistenceService().get_job(existing_session, JOB_ID)) is job
    assert run(JobPersistenceService().get_job(missing_session, OTHER_JOB_ID)) is None
    assert "FOR UPDATE" not in str(existing_session.executed[0]).upper()
    assert_no_write(existing_session)
    assert_no_write(missing_session)


def test_list_jobs_for_run_has_one_ordered_query_and_missing_is_empty():
    jobs = [make_job(job_id=JOB_ID), make_job(job_id=OTHER_JOB_ID)]
    session = FakeSession([ExecuteResult(scalars=jobs)])
    assert run(JobPersistenceService().list_jobs_for_run(session, "run-1")) == jobs
    statement = session.executed[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "WHERE jobs.marketing_run_id =" in sql
    assert "ORDER BY jobs.created_at ASC, jobs.job_id ASC" in sql
    assert "FOR UPDATE" not in sql
    assert_no_write(session)

    empty = FakeSession([ExecuteResult(scalars=[])])
    assert run(JobPersistenceService().list_jobs_for_run(empty, "missing")) == []
    with pytest.raises(InvalidJobDataError):
        run(JobPersistenceService().list_jobs_for_run(object(), ""))


@pytest.mark.parametrize(
    "expected_version",
    [True, False, -1, MAX_JOB_VERSION + 1, 1.0, "1", None],
)
def test_expected_version_type_and_range_precede_session(expected_version):
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService().transition_job(
                object(), JOB_ID, expected_version, JobStatus.RUNNING
            )
        )


def test_expected_version_integer_subclass_and_raw_status_reject_before_session():
    class IntegerSubclass(int):
        pass

    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService().transition_job(
                object(), JOB_ID, IntegerSubclass(0), JobStatus.RUNNING
            )
        )
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService().transition_job(
                object(), JOB_ID, 0, "running"
            )
        )


def test_expected_version_is_mandatory_at_call_binding():
    with pytest.raises(TypeError):
        JobPersistenceService().transition_job(
            object(), JOB_ID, to_status=JobStatus.RUNNING
        )


@pytest.mark.parametrize(
    "status,kwargs",
    [
        (JobStatus.RUNNING, {"result_json": {}}),
        (JobStatus.RUNNING, {"error": "failure"}),
        (JobStatus.SUCCEEDED, {}),
        (JobStatus.SUCCEEDED, {"result_json": {}, "error": "failure"}),
        (JobStatus.FAILED, {}),
        (JobStatus.FAILED, {"result_json": {}, "error": "failure"}),
    ],
)
def test_outcome_presence_rules_precede_session(status, kwargs):
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService().transition_job(
                object(), JOB_ID, 0, status, **kwargs
            )
        )


@pytest.mark.parametrize("error", ["", "\t\n\v\f\r ", "x" * 4001, "bad\x00", "\ud800"])
def test_failure_error_validation_precedes_session(error):
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService().transition_job(
                object(), JOB_ID, 1, JobStatus.FAILED, error=error
            )
        )


def test_failure_error_requires_exact_string_without_stringification():
    class ErrorWithString:
        def __str__(self):
            raise AssertionError("must not stringify")

    class StringSubclass(str):
        pass

    for value in (RuntimeError("secret"), ErrorWithString(), StringSubclass("safe")):
        with pytest.raises(InvalidJobDataError):
            run(
                JobPersistenceService().transition_job(
                    object(), JOB_ID, 1, JobStatus.FAILED, error=value
                )
            )


def test_failure_error_boundaries_and_exact_preservation():
    for error in ("x", "x" * 4000, "\u2003"):
        job = make_job(JobStatus.RUNNING, version=1)
        session = FakeSession([ExecuteResult(scalar=job)])
        result = run(
            JobPersistenceService(lambda: COMPLETED).transition_job(
                session, JOB_ID, 1, JobStatus.FAILED, error=error
            )
        )
        assert result.error == error
        assert result.result_json is None


def test_pending_to_running_sets_exact_state_and_scoped_flush():
    clock = CountingClock(STARTED)
    job = make_job()
    session = FakeSession([ExecuteResult(scalar=job)])

    result = run(
        JobPersistenceService(clock).transition_job(
            session, JOB_ID, 0, JobStatus.RUNNING
        )
    )

    assert result is job
    assert job.status is JobStatus.RUNNING and job.version == 1
    assert job.started_at == job.updated_at == STARTED
    assert job.completed_at is job.result_json is job.error is None
    assert clock.calls == 1
    assert session.flush_arguments == [[job]]
    sql = str(session.executed[0].compile(dialect=postgresql.dialect()))
    assert "WHERE jobs.job_id =" in sql and "FOR UPDATE" in sql
    assert session.executed[0].get_execution_options()["populate_existing"] is True


def test_running_to_succeeded_sets_exact_state_and_copies_result():
    job = make_job(JobStatus.RUNNING, version=1)
    session = FakeSession([ExecuteResult(scalar=job)])
    original = {"nested": {"ok": True}}
    result = run(
        JobPersistenceService(lambda: COMPLETED).transition_job(
            session,
            JOB_ID,
            1,
            JobStatus.SUCCEEDED,
            result_json=original,
        )
    )
    original["nested"]["ok"] = False
    assert result.status is JobStatus.SUCCEEDED and result.version == 2
    assert result.result_json == {"nested": {"ok": True}}
    assert result.error is None
    assert result.completed_at == result.updated_at == COMPLETED
    assert result.started_at == STARTED


def test_running_to_failed_sets_exact_state():
    job = make_job(JobStatus.RUNNING, version=1)
    session = FakeSession([ExecuteResult(scalar=job)])
    result = run(
        JobPersistenceService(lambda: COMPLETED).transition_job(
            session,
            JOB_ID,
            1,
            JobStatus.FAILED,
            error="sanitized failure",
        )
    )
    assert result.status is JobStatus.FAILED and result.version == 2
    assert result.error == "sanitized failure" and result.result_json is None
    assert result.completed_at == result.updated_at == COMPLETED


ILLEGAL_EDGES = (
    (JobStatus.PENDING, 0, JobStatus.PENDING, {}),
    (JobStatus.PENDING, 0, JobStatus.SUCCEEDED, {"result_json": {}}),
    (JobStatus.PENDING, 0, JobStatus.FAILED, {"error": "failure"}),
    (JobStatus.RUNNING, 1, JobStatus.PENDING, {}),
    (JobStatus.RUNNING, 1, JobStatus.RUNNING, {}),
    (JobStatus.SUCCEEDED, 2, JobStatus.PENDING, {}),
    (JobStatus.SUCCEEDED, 2, JobStatus.RUNNING, {}),
    (JobStatus.SUCCEEDED, 2, JobStatus.SUCCEEDED, {"result_json": {}}),
    (JobStatus.SUCCEEDED, 2, JobStatus.FAILED, {"error": "failure"}),
    (JobStatus.FAILED, 2, JobStatus.PENDING, {}),
    (JobStatus.FAILED, 2, JobStatus.RUNNING, {}),
    (JobStatus.FAILED, 2, JobStatus.SUCCEEDED, {"result_json": {}}),
    (JobStatus.FAILED, 2, JobStatus.FAILED, {"error": "failure"}),
)


@pytest.mark.parametrize("current,version,target,kwargs", ILLEGAL_EDGES)
def test_every_illegal_edge_is_typed_and_has_no_clock_mutation_or_flush(
    current, version, target, kwargs
):
    clock = CountingClock()
    job = make_job(current, version=version)
    before = dict(job.__dict__)
    session = FakeSession([ExecuteResult(scalar=job)])

    with pytest.raises(IllegalJobTransitionError):
        run(
            JobPersistenceService(clock).transition_job(
                session, JOB_ID, version, target, **kwargs
            )
        )

    assert job.__dict__ == before
    assert clock.calls == 0
    assert session.flush_arguments == []


def test_valid_missing_precedes_stale_illegal_and_clock():
    clock = CountingClock()
    session = FakeSession([ExecuteResult(scalar=None)])
    with pytest.raises(JobNotFoundError):
        run(
            JobPersistenceService(clock).transition_job(
                session, JOB_ID, 99, JobStatus.RUNNING
            )
        )
    assert clock.calls == 0
    assert session.flush_arguments == []


def test_stale_precedes_legality_clock_and_mutation():
    clock = CountingClock()
    job = make_job(JobStatus.SUCCEEDED, version=2)
    before = dict(job.__dict__)
    session = FakeSession([ExecuteResult(scalar=job)])
    with pytest.raises(StaleJobVersionError):
        run(
            JobPersistenceService(clock).transition_job(
                session, JOB_ID, 1, JobStatus.FAILED, error="failure"
            )
        )
    assert job.__dict__ == before
    assert clock.calls == 0
    assert session.flush_arguments == []

    current = FakeSession([ExecuteResult(scalar=job)])
    with pytest.raises(IllegalJobTransitionError):
        run(
            JobPersistenceService(clock).transition_job(
                current, JOB_ID, 2, JobStatus.FAILED, error="failure"
            )
        )


def test_exhausted_version_precedes_illegality_clock_and_increment():
    clock = CountingClock()
    job = make_job(JobStatus.PENDING, version=MAX_JOB_VERSION)
    before = dict(job.__dict__)
    session = FakeSession([ExecuteResult(scalar=job)])

    with pytest.raises(JobVersionExhaustedError):
        run(
            JobPersistenceService(clock).transition_job(
                session, JOB_ID, MAX_JOB_VERSION, JobStatus.FAILED, error="failure"
            )
        )
    assert job.__dict__ == before
    assert job.version == MAX_JOB_VERSION
    assert clock.calls == 0
    assert session.flush_arguments == []


@pytest.mark.parametrize(
    "job,target,kwargs,clock_value",
    [
        (make_job(), JobStatus.RUNNING, {}, CREATED - timedelta(microseconds=1)),
        (
            make_job(JobStatus.RUNNING, version=1),
            JobStatus.SUCCEEDED,
            {"result_json": {}},
            STARTED - timedelta(microseconds=1),
        ),
    ],
)
def test_backward_clock_rejects_without_lifecycle_mutation_or_flush(
    job, target, kwargs, clock_value
):
    before = dict(job.__dict__)
    session = FakeSession([ExecuteResult(scalar=job)])
    with pytest.raises(InvalidJobDataError):
        run(
            JobPersistenceService(lambda: clock_value).transition_job(
                session, JOB_ID, job.version, target, **kwargs
            )
        )
    assert job.__dict__ == before
    assert session.flush_arguments == []


def test_flush_error_passes_through_without_service_rollback():
    failure = RuntimeError("database failure")
    job = make_job()
    session = FakeSession([ExecuteResult(scalar=job)], flush_error=failure)
    with pytest.raises(RuntimeError) as raised:
        run(
            JobPersistenceService(lambda: STARTED).transition_job(
                session, JOB_ID, 0, JobStatus.RUNNING
            )
        )
    assert raised.value is failure
    assert session.flush_arguments == [[job]]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class TrackedSessionFacade:
    """Async-shaped adapter around a real SQLAlchemy identity map.

    SQLite is used only for service/ORM unit evidence. PostgreSQL migration,
    constraint, locking, and concurrency evidence remains separately gated.
    """

    def __init__(self, sync_session):
        self.sync_session = sync_session
        self.executed = []
        self.flush_arguments = []

    @property
    def identity_map(self):
        return self.sync_session.identity_map

    @property
    def deleted(self):
        return self.sync_session.deleted

    @property
    def no_autoflush(self):
        return self.sync_session.no_autoflush

    async def execute(self, statement):
        self.executed.append(statement)
        result = self.sync_session.execute(statement)
        scalar_value = result.scalar_one_or_none()
        # SQLite returns naive DateTime values. Restore the timezone annotation
        # that PostgreSQL preserves so service logic is tested at its real type
        # boundary without pretending this adapter is PostgreSQL evidence.
        for mapped_value in self.sync_session.identity_map.values():
            if not isinstance(mapped_value, Job):
                continue
            for field in ("created_at", "updated_at", "started_at", "completed_at"):
                current = getattr(mapped_value, field)
                if current is not None and current.tzinfo is None:
                    set_committed_value(
                        mapped_value, field, current.replace(tzinfo=timezone.utc)
                    )
        return ExecuteResult(scalar=scalar_value)

    def add(self, value):
        self.sync_session.add(value)

    async def flush(self, objects=None):
        self.flush_arguments.append(objects)
        self.sync_session.flush(objects)


def make_identity_session():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                telegram_id BIGINT NOT NULL UNIQUE,
                username VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                created_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE marketing_runs (
                run_id VARCHAR(64) PRIMARY KEY,
                user_id INTEGER,
                workflow_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                current_step VARCHAR(64),
                input_json JSON,
                state_json JSON,
                error TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE jobs (
                job_id VARCHAR(32) PRIMARY KEY,
                user_id INTEGER,
                marketing_run_id VARCHAR(64),
                workflow_step VARCHAR(64),
                kind VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                version INTEGER NOT NULL,
                payload_json JSON NOT NULL,
                result_json JSON,
                error VARCHAR(4000),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                started_at DATETIME,
                completed_at DATETIME
            )
            """
        )
    sync_session = Session(engine, expire_on_commit=False)
    return sync_session, TrackedSessionFacade(sync_session)


def persist_target(sync_session, *, owner=None, status=JobStatus.PENDING):
    version = 0 if status is JobStatus.PENDING else 1
    target = make_job(status, version=version)
    if isinstance(owner, User):
        target.user = owner
    elif isinstance(owner, MarketingRun):
        target.marketing_run = owner
    if owner is not None:
        sync_session.add(owner)
    sync_session.add(target)
    sync_session.commit()
    return target


def reject_dirty(sync_session, facade, target):
    clock = CountingClock()
    before = dict(target.__dict__)
    with pytest.raises(DirtyJobMutationError) as raised:
        run(
            JobPersistenceService(clock).transition_job(
                facade, JOB_ID, 0, JobStatus.RUNNING
            )
        )
    assert str(raised.value) == (
        "Job has pending protected mutations; roll back the caller-owned transaction"
    )
    assert target.__dict__ == before
    assert facade.executed == []
    assert facade.flush_arguments == []
    assert clock.calls == 0


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("job_id", OTHER_JOB_ID),
        ("user_id", 9),
        ("marketing_run_id", "other-run"),
        ("workflow_step", "other.step"),
        ("kind", "other.kind"),
        ("payload_json", {"reassigned": True}),
        ("created_at", CREATED + timedelta(seconds=1)),
        ("version", 7),
    ],
)
def test_tracked_protected_scalar_history_rejects_before_sql(attribute, value):
    sync_session, facade = make_identity_session()
    try:
        target = persist_target(sync_session)
        setattr(target, attribute, value)
        reject_dirty(sync_session, facade, target)
        assert getattr(target, attribute) == value
        assert sync_session.is_modified(target, include_collections=True)
    finally:
        sync_session.close()


def test_explicitly_flagged_in_place_payload_history_rejects_before_sql():
    from sqlalchemy.orm.attributes import flag_modified

    sync_session, facade = make_identity_session()
    try:
        target = persist_target(sync_session)
        target.payload_json["local"] = True
        flag_modified(target, "payload_json")
        reject_dirty(sync_session, facade, target)
        assert target.payload_json == {"seed": True, "local": True}
    finally:
        sync_session.close()


def test_target_user_relationship_reassignment_rejects_before_sql():
    sync_session, facade = make_identity_session()
    try:
        first = User(id=1, telegram_id=10)
        second = User(id=2, telegram_id=20)
        target = persist_target(sync_session, owner=first)
        sync_session.add(second)
        target.user = second
        reject_dirty(sync_session, facade, target)
        assert target.user is second
        sync_session.rollback()
        restored = sync_session.get(Job, JOB_ID)
        assert restored.user_id == 1 and restored.marketing_run_id is None
        assert restored.status is JobStatus.PENDING and restored.version == 0
    finally:
        sync_session.close()


def test_target_run_relationship_reassignment_rejects_before_sql():
    sync_session, facade = make_identity_session()
    try:
        first = MarketingRun(run_id="run-1", workflow_type="mvp")
        second = MarketingRun(run_id="run-2", workflow_type="mvp")
        target = persist_target(sync_session, owner=first)
        sync_session.add(second)
        target.marketing_run = second
        reject_dirty(sync_session, facade, target)
        assert target.marketing_run is second
        sync_session.rollback()
        restored = sync_session.get(Job, JOB_ID)
        assert restored.marketing_run_id == "run-1" and restored.user_id is None
        assert restored.status is JobStatus.PENDING and restored.version == 0
    finally:
        sync_session.close()


@pytest.mark.parametrize("owner_type", [User, MarketingRun])
@pytest.mark.parametrize("operation", ["append", "remove"])
def test_identity_mapped_owner_collection_changes_reject_before_sql(
    owner_type, operation
):
    sync_session, facade = make_identity_session()
    try:
        if owner_type is User:
            owner = User(id=1, telegram_id=10)
        else:
            owner = MarketingRun(run_id="run-1", workflow_type="mvp")
        target = persist_target(
            sync_session, owner=owner if operation == "remove" else None
        )
        if operation == "append":
            sync_session.add(owner)
            owner.jobs.append(target)
        else:
            assert target in owner.jobs
            owner.jobs.remove(target)
        reject_dirty(sync_session, facade, target)
        sync_session.rollback()
        restored = sync_session.get(Job, JOB_ID)
        if operation == "append":
            assert restored.user_id is None and restored.marketing_run_id is None
        elif owner_type is User:
            assert restored.user_id == 1 and restored.marketing_run_id is None
        else:
            assert restored.marketing_run_id == "run-1" and restored.user_id is None
        assert restored.status is JobStatus.PENDING and restored.version == 0
    finally:
        sync_session.close()


def test_pending_target_deletion_rejects_before_sql():
    sync_session, facade = make_identity_session()
    try:
        target = persist_target(sync_session)
        sync_session.delete(target)
        reject_dirty(sync_session, facade, target)
        assert target in sync_session.deleted
    finally:
        sync_session.close()


def test_conflicting_owner_histories_reject_once_and_caller_rollback_restores():
    sync_session, facade = make_identity_session()
    try:
        user = User(id=1, telegram_id=10)
        run_owner = MarketingRun(run_id="run-1", workflow_type="mvp")
        target = persist_target(sync_session, owner=user)
        sync_session.add(run_owner)
        run_owner.jobs.append(target)
        target.user = None

        reject_dirty(sync_session, facade, target)
        sync_session.rollback()
        restored = sync_session.get(Job, JOB_ID)
        assert restored.user_id == 1
        assert restored.marketing_run_id is None
        assert restored.status is JobStatus.PENDING
        assert restored.version == 0
    finally:
        sync_session.close()


def test_unrelated_owner_collection_history_does_not_block_target():
    sync_session, facade = make_identity_session()
    try:
        target = persist_target(sync_session)
        user = User(id=1, telegram_id=10)
        unrelated = make_job(job_id=OTHER_JOB_ID)
        sync_session.add(user)
        user.jobs.append(unrelated)

        result = run(
            JobPersistenceService(lambda: STARTED).transition_job(
                facade, JOB_ID, 0, JobStatus.RUNNING
            )
        )
        assert result.status is JobStatus.RUNNING and result.version == 1
        assert unrelated in user.jobs
        assert unrelated in sync_session.new
    finally:
        sync_session.close()


@pytest.mark.parametrize("owner_type", [User, MarketingRun])
def test_removing_job_from_loaded_aggregate_uses_delete_orphan(owner_type):
    sync_session, _facade = make_identity_session()
    try:
        if owner_type is User:
            owner = User(id=1, telegram_id=10)
        else:
            owner = MarketingRun(run_id="run-1", workflow_type="mvp")
        target = persist_target(sync_session, owner=owner)
        assert target in owner.jobs
        owner.jobs.remove(target)
        sync_session.flush()
        assert sync_session.get(Job, JOB_ID) is None
    finally:
        sync_session.close()


@pytest.mark.parametrize("owner_type", [User, MarketingRun])
def test_deleting_owner_with_loaded_collection_deletes_job_in_orm(owner_type):
    sync_session, _facade = make_identity_session()
    try:
        if owner_type is User:
            owner = User(id=1, telegram_id=10)
        else:
            owner = MarketingRun(run_id="run-1", workflow_type="mvp")
        persist_target(sync_session, owner=owner)
        assert len(owner.jobs) == 1
        if owner_type is User:
            set_committed_value(owner, "tasks", [])
            set_committed_value(owner, "brand_profile", None)
            set_committed_value(owner, "marketing_runs", [])
        else:
            set_committed_value(owner, "artifacts", [])
        sync_session.delete(owner)
        sync_session.flush()
        assert sync_session.get(Job, JOB_ID) is None
    finally:
        sync_session.close()


@pytest.mark.parametrize("nested", [False, True])
def test_untracked_in_place_payload_is_reloaded_and_does_not_persist(nested):
    sync_session, facade = make_identity_session()
    try:
        target = make_job(payload_json={"top": 1, "nested": {"value": 1}})
        sync_session.add(target)
        sync_session.commit()
        if nested:
            target.payload_json["nested"]["value"] = 99
        else:
            target.payload_json["top"] = 99
        assert not sync_session.is_modified(target, include_collections=True)

        result = run(
            JobPersistenceService(lambda: STARTED).transition_job(
                facade, JOB_ID, 0, JobStatus.RUNNING
            )
        )
        assert result.payload_json == {"top": 1, "nested": {"value": 1}}
        assert result.status is JobStatus.RUNNING and result.version == 1
        assert facade.flush_arguments == [[target]]
    finally:
        sync_session.close()


def test_unrelated_dirty_new_and_deleted_state_survives_target_transition():
    sync_session, facade = make_identity_session()
    try:
        target = persist_target(sync_session)
        dirty = make_job(job_id=OTHER_JOB_ID)
        deleted = make_job(job_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        sync_session.add_all([dirty, deleted])
        sync_session.commit()
        dirty.kind = "locally.changed"
        pending = make_job(job_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        sync_session.add(pending)
        sync_session.delete(deleted)

        run(
            JobPersistenceService(lambda: STARTED).transition_job(
                facade, JOB_ID, 0, JobStatus.RUNNING
            )
        )

        assert dirty in sync_session.dirty and dirty.kind == "locally.changed"
        assert pending in sync_session.new
        assert deleted in sync_session.deleted
        assert target.status is JobStatus.RUNNING and target.version == 1
    finally:
        sync_session.close()
