from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.util import identity_key

from app.models import Job, JobStatus, MarketingRun, User


MAX_JOB_VERSION = 2_147_483_647
MIN_JSON_INTEGER = -(2**63)
MAX_JSON_INTEGER = 2**63 - 1
MAX_JSON_DEPTH = 16
MAX_PAYLOAD_BYTES = 262_144
MAX_RESULT_BYTES = 1_048_576
MAX_ERROR_CHARACTERS = 4_000

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CANONICAL_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ASCII_EDGE_WHITESPACE = "\t\n\v\f\r "
_PROTECTED_JOB_ATTRIBUTES = (
    "job_id",
    "user_id",
    "marketing_run_id",
    "workflow_step",
    "kind",
    "payload_json",
    "created_at",
    "version",
)


class JobPersistenceError(Exception):
    """Base class for stable Job persistence domain errors."""


class InvalidJobDataError(JobPersistenceError):
    """A Job identifier, owner, outcome, error, version, or clock is invalid."""


class InvalidJobJsonError(InvalidJobDataError):
    """A Job JSON value is outside the approved recursive domain."""


class JobJsonTooLargeError(InvalidJobDataError):
    """A canonical Job JSON value exceeds its approved byte limit."""


class DirtyJobMutationError(JobPersistenceError):
    """The target Job has unsupported pending caller-owned mutation history."""


class JobNotFoundError(JobPersistenceError):
    """A syntactically valid transition target does not exist."""


class StaleJobVersionError(JobPersistenceError):
    """The locked Job version differs from the caller's observed version."""


class JobVersionExhaustedError(JobPersistenceError):
    """The locked Job version cannot be incremented within INTEGER range."""


class IllegalJobTransitionError(JobPersistenceError):
    """The locked Job state cannot legally precede the requested state."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_exact_string(value: Any, field: str) -> str:
    if type(value) is not str:
        raise InvalidJobDataError(f"{field} must be an exact string")
    _validate_unicode(value, field)
    return value


def _validate_unicode(value: str, field: str) -> None:
    if "\x00" in value:
        raise InvalidJobDataError(f"{field} contains unsupported Unicode")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise InvalidJobDataError(f"{field} contains invalid Unicode") from exc


def _validate_job_id(job_id: Any) -> str:
    value = _require_exact_string(job_id, "job_id")
    if _JOB_ID_RE.fullmatch(value) is None:
        raise InvalidJobDataError("job_id has invalid format")
    return value


def _validate_canonical_key(value: Any, field: str) -> str:
    text_value = _require_exact_string(value, field)
    if _CANONICAL_KEY_RE.fullmatch(text_value) is None:
        raise InvalidJobDataError(f"{field} has invalid format")
    return text_value


def _validate_optional_canonical_key(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _validate_canonical_key(value, field)


def _validate_run_id(value: Any) -> str:
    run_id = _require_exact_string(value, "marketing_run_id")
    if not 1 <= len(run_id) <= 64:
        raise InvalidJobDataError("marketing_run_id has invalid length")
    return run_id


def _validate_optional_run_id(value: Any) -> str | None:
    if value is None:
        return None
    return _validate_run_id(value)


def _validate_optional_user_id(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value <= 0:
        raise InvalidJobDataError("user_id must be a positive exact integer")
    return value


def _validate_expected_version(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_JOB_VERSION:
        raise InvalidJobDataError("expected_version is outside the supported range")
    return value


def _validate_target_status(value: Any) -> JobStatus:
    if type(value) is not JobStatus:
        raise InvalidJobDataError("to_status must be an exact JobStatus")
    return value


def _validate_json_unicode(value: str, field: str) -> None:
    try:
        _validate_unicode(value, field)
    except InvalidJobDataError as exc:
        raise InvalidJobJsonError(str(exc)) from exc


def _validate_json_node(
    value: Any,
    *,
    field: str,
    depth: int,
    active_containers: set[int],
) -> None:
    value_type = type(value)
    if value_type is dict:
        if depth > MAX_JSON_DEPTH:
            raise InvalidJobJsonError(f"{field} exceeds maximum container depth")
        marker = id(value)
        if marker in active_containers:
            raise InvalidJobJsonError(f"{field} contains a cycle")
        active_containers.add(marker)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise InvalidJobJsonError(f"{field} contains a non-string key")
                _validate_json_unicode(key, field)
                _validate_json_node(
                    item,
                    field=field,
                    depth=depth + 1,
                    active_containers=active_containers,
                )
        finally:
            active_containers.remove(marker)
        return

    if value_type is list:
        if depth > MAX_JSON_DEPTH:
            raise InvalidJobJsonError(f"{field} exceeds maximum container depth")
        marker = id(value)
        if marker in active_containers:
            raise InvalidJobJsonError(f"{field} contains a cycle")
        active_containers.add(marker)
        try:
            for item in value:
                _validate_json_node(
                    item,
                    field=field,
                    depth=depth + 1,
                    active_containers=active_containers,
                )
        finally:
            active_containers.remove(marker)
        return

    if value is None or value_type is bool:
        return
    if value_type is int:
        if not MIN_JSON_INTEGER <= value <= MAX_JSON_INTEGER:
            raise InvalidJobJsonError(f"{field} contains an out-of-range integer")
        return
    if value_type is float:
        if not math.isfinite(value):
            raise InvalidJobJsonError(f"{field} contains a non-finite number")
        return
    if value_type is str:
        _validate_json_unicode(value, field)
        return
    raise InvalidJobJsonError(f"{field} contains an unsupported value type")


def _validate_and_copy_json(
    value: Any,
    *,
    field: str,
    byte_limit: int,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise InvalidJobJsonError(f"{field} must be an exact dictionary")
    _validate_json_node(
        value,
        field=field,
        depth=1,
        active_containers=set(),
    )
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise InvalidJobJsonError(f"{field} cannot be serialized") from exc
    if len(canonical) > byte_limit:
        raise JobJsonTooLargeError(f"{field} exceeds its canonical byte limit")
    return copy.deepcopy(value)


def _validate_payload(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    return _validate_and_copy_json(
        value,
        field="payload_json",
        byte_limit=MAX_PAYLOAD_BYTES,
    )


def _validate_result(value: Any) -> dict[str, Any]:
    return _validate_and_copy_json(
        value,
        field="result_json",
        byte_limit=MAX_RESULT_BYTES,
    )


def _validate_error(value: Any) -> str:
    error = _require_exact_string(value, "error")
    if not 1 <= len(error) <= MAX_ERROR_CHARACTERS:
        raise InvalidJobDataError("error has invalid length")
    if error.strip(_ASCII_EDGE_WHITESPACE) == "":
        raise InvalidJobDataError("error must contain non-whitespace text")
    return error


def _normalize_clock_value(value: Any) -> datetime:
    if type(value) is not datetime:
        raise InvalidJobDataError("clock must return an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidJobDataError("clock must return an aware datetime")
    return value.astimezone(timezone.utc)


def _history_contains_target(
    values: Iterable[Any],
    target: Job,
    job_id: str,
) -> bool:
    for value in values:
        if value is target:
            return True
        state = sa_inspect(value)
        if state.identity == (job_id,) or state.dict.get("job_id") == job_id:
            return True
    return False


def _reject_dirty_target(db_session: AsyncSession, job_id: str) -> None:
    target = db_session.identity_map.get(identity_key(Job, (job_id,)))
    if target is None:
        return

    state = sa_inspect(target)
    dirty = any(
        state.attrs[field].history.has_changes()
        for field in _PROTECTED_JOB_ATTRIBUTES
    )
    dirty = dirty or state.attrs.user.history.has_changes()
    dirty = dirty or state.attrs.marketing_run.history.has_changes()

    for value in tuple(db_session.identity_map.values()):
        if isinstance(value, User):
            history = sa_inspect(value).attrs.jobs.history
        elif isinstance(value, MarketingRun):
            history = sa_inspect(value).attrs.jobs.history
        else:
            continue
        if _history_contains_target(history.added, target, job_id) or (
            _history_contains_target(history.deleted, target, job_id)
        ):
            dirty = True

    dirty = dirty or target in db_session.deleted
    if dirty:
        raise DirtyJobMutationError(
            "Job has pending protected mutations; roll back the caller-owned "
            "transaction"
        )


def _validate_final_state(job: Job) -> None:
    if job.version < 0 or job.version > MAX_JOB_VERSION:
        raise InvalidJobDataError("Job lifecycle state is incoherent")
    if job.updated_at < job.created_at:
        raise InvalidJobDataError("Job lifecycle state is incoherent")

    if job.status is JobStatus.PENDING:
        coherent = (
            job.started_at is None
            and job.completed_at is None
            and job.result_json is None
            and job.error is None
            and job.updated_at == job.created_at
        )
    elif job.status is JobStatus.RUNNING:
        coherent = (
            job.started_at is not None
            and job.completed_at is None
            and job.result_json is None
            and job.error is None
            and job.updated_at == job.started_at
            and job.started_at >= job.created_at
        )
    elif job.status is JobStatus.SUCCEEDED:
        coherent = (
            job.started_at is not None
            and job.completed_at is not None
            and job.result_json is not None
            and job.error is None
            and job.updated_at == job.completed_at
            and job.completed_at >= job.started_at >= job.created_at
        )
    elif job.status is JobStatus.FAILED:
        coherent = (
            job.started_at is not None
            and job.completed_at is not None
            and job.result_json is None
            and job.error is not None
            and job.error.strip(_ASCII_EDGE_WHITESPACE) != ""
            and job.updated_at == job.completed_at
            and job.completed_at >= job.started_at >= job.created_at
        )
    else:
        coherent = False

    if not coherent:
        raise InvalidJobDataError("Job lifecycle state is incoherent")


class JobPersistenceService:
    """Caller-transaction-owned durable Job persistence operations."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        if clock is not None and not callable(clock):
            raise InvalidJobDataError("Job clock must be callable")
        self._clock = clock or _utc_now

    def _now(self) -> datetime:
        return _normalize_clock_value(self._clock())

    async def create_job(
        self,
        db_session: AsyncSession,
        *,
        kind: str,
        payload_json: dict[str, Any] | None = None,
        user_id: int | None = None,
        marketing_run_id: str | None = None,
        workflow_step: str | None = None,
        job_id: str | None = None,
    ) -> Job:
        validated_kind = _validate_canonical_key(kind, "kind")
        validated_user_id = _validate_optional_user_id(user_id)
        validated_run_id = _validate_optional_run_id(marketing_run_id)
        validated_step = _validate_optional_canonical_key(
            workflow_step,
            "workflow_step",
        )
        validated_job_id = None if job_id is None else _validate_job_id(job_id)

        if validated_user_id is not None and validated_run_id is not None:
            raise InvalidJobDataError("Job owner combination is invalid")
        if validated_step is not None and validated_run_id is None:
            raise InvalidJobDataError("workflow_step requires a MarketingRun owner")

        copied_payload = _validate_payload(payload_json)

        with db_session.no_autoflush:
            if validated_user_id is not None:
                result = await db_session.execute(
                    select(User).where(User.id == validated_user_id)
                )
                if result.scalar_one_or_none() is None:
                    raise InvalidJobDataError("Job owner does not exist")
            elif validated_run_id is not None:
                result = await db_session.execute(
                    select(MarketingRun).where(
                        MarketingRun.run_id == validated_run_id
                    )
                )
                if result.scalar_one_or_none() is None:
                    raise InvalidJobDataError("Job owner does not exist")

        instant = self._now()
        values: dict[str, Any] = {
            "user_id": validated_user_id,
            "marketing_run_id": validated_run_id,
            "workflow_step": validated_step,
            "kind": validated_kind,
            "status": JobStatus.PENDING,
            "version": 0,
            "payload_json": copied_payload,
            "result_json": None,
            "error": None,
            "created_at": instant,
            "updated_at": instant,
            "started_at": None,
            "completed_at": None,
        }
        if validated_job_id is not None:
            values["job_id"] = validated_job_id
        job = Job(**values)
        _validate_final_state(job)
        db_session.add(job)
        await db_session.flush([job])
        return job

    async def get_job(
        self,
        db_session: AsyncSession,
        job_id: str,
    ) -> Job | None:
        validated_job_id = _validate_job_id(job_id)
        with db_session.no_autoflush:
            result = await db_session.execute(
                select(Job).where(Job.job_id == validated_job_id)
            )
        return result.scalar_one_or_none()

    async def list_jobs_for_run(
        self,
        db_session: AsyncSession,
        marketing_run_id: str,
    ) -> list[Job]:
        validated_run_id = _validate_run_id(marketing_run_id)
        with db_session.no_autoflush:
            result = await db_session.execute(
                select(Job)
                .where(Job.marketing_run_id == validated_run_id)
                .order_by(Job.created_at.asc(), Job.job_id.asc())
            )
        return list(result.scalars().all())

    async def transition_job(
        self,
        db_session: AsyncSession,
        job_id: str,
        expected_version: int,
        to_status: JobStatus,
        *,
        result_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Job:
        validated_job_id = _validate_job_id(job_id)
        validated_version = _validate_expected_version(expected_version)
        validated_status = _validate_target_status(to_status)

        copied_result: dict[str, Any] | None = None
        validated_error: str | None = None
        if validated_status is JobStatus.SUCCEEDED:
            if result_json is None or error is not None:
                raise InvalidJobDataError("Succeeded transition outcome is invalid")
            copied_result = _validate_result(result_json)
        elif validated_status is JobStatus.FAILED:
            if result_json is not None or error is None:
                raise InvalidJobDataError("Failed transition outcome is invalid")
            validated_error = _validate_error(error)
        elif result_json is not None or error is not None:
            raise InvalidJobDataError("Transition outcome is invalid")

        with db_session.no_autoflush:
            _reject_dirty_target(db_session, validated_job_id)
            result = await db_session.execute(
                select(Job)
                .where(Job.job_id == validated_job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        job = result.scalar_one_or_none()
        if job is None:
            raise JobNotFoundError("Job does not exist")
        if job.version != validated_version:
            raise StaleJobVersionError("Job version is stale")
        if job.version == MAX_JOB_VERSION:
            raise JobVersionExhaustedError("Job version is exhausted")

        legal = (
            job.status is JobStatus.PENDING
            and validated_status is JobStatus.RUNNING
        ) or (
            job.status is JobStatus.RUNNING
            and validated_status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
        )
        if not legal:
            raise IllegalJobTransitionError("Job transition is illegal")

        instant = self._now()
        if instant < job.created_at:
            raise InvalidJobDataError("Transition clock precedes Job creation")
        if (
            validated_status in (JobStatus.SUCCEEDED, JobStatus.FAILED)
            and (job.started_at is None or instant < job.started_at)
        ):
            raise InvalidJobDataError("Transition clock precedes Job start")

        job.status = validated_status
        job.updated_at = instant
        if validated_status is JobStatus.RUNNING:
            job.started_at = instant
        else:
            job.completed_at = instant
            job.result_json = copied_result
            job.error = validated_error
        job.version += 1

        _validate_final_state(job)
        await db_session.flush([job])
        return job


__all__ = [
    "DirtyJobMutationError",
    "IllegalJobTransitionError",
    "InvalidJobDataError",
    "InvalidJobJsonError",
    "JobJsonTooLargeError",
    "JobNotFoundError",
    "JobPersistenceError",
    "JobPersistenceService",
    "JobVersionExhaustedError",
    "MAX_JOB_VERSION",
    "StaleJobVersionError",
]
