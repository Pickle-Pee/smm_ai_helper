from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import CheckConstraint, Enum as SAEnum, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import MANYTOONE, ONETOMANY

from app.models import Job, JobStatus, MarketingRun, User


EXPECTED_COLUMNS = (
    "job_id",
    "user_id",
    "marketing_run_id",
    "workflow_step",
    "kind",
    "status",
    "version",
    "payload_json",
    "result_json",
    "error",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
)

EXPECTED_CHECKS = {
    "ck_jobs_job_id_format",
    "ck_jobs_kind_format",
    "ck_jobs_workflow_step_format",
    "ck_jobs_exclusive_owner",
    "ck_jobs_step_requires_run",
    "ck_jobs_status",
    "ck_jobs_version_nonnegative",
    "ck_jobs_payload_object",
    "ck_jobs_result_object",
    "ck_jobs_lifecycle",
    "ck_jobs_timestamp_order",
}


def _normalized(value: object) -> str:
    return " ".join(str(value).split())


def test_job_status_is_exact_closed_ordered_vocabulary():
    assert tuple(JobStatus) == (
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
    )
    assert tuple(item.value for item in JobStatus) == (
        "pending",
        "running",
        "succeeded",
        "failed",
    )
    assert len(JobStatus.__members__) == 4


def test_job_has_exact_fourteen_column_contract():
    assert tuple(Job.__table__.columns.keys()) == EXPECTED_COLUMNS
    assert Job.__table__.primary_key.columns.keys() == ["job_id"]

    columns = Job.__table__.columns
    assert columns.job_id.type.length == 32
    assert columns.user_id.nullable is True
    assert columns.marketing_run_id.type.length == 64
    assert columns.marketing_run_id.nullable is True
    assert columns.workflow_step.type.length == 64
    assert columns.kind.type.length == 64
    assert isinstance(columns.status.type, SAEnum)
    assert columns.status.type.native_enum is False
    assert columns.status.type.length == 32
    assert columns.status.type.enum_class is JobStatus
    assert columns.version.nullable is False
    assert isinstance(columns.payload_json.type, JSONB)
    assert isinstance(columns.result_json.type, JSONB)
    assert columns.result_json.type.none_as_null is True
    assert columns.error.type.length == 4000
    assert columns.created_at.type.timezone is True
    assert columns.updated_at.type.timezone is True
    assert columns.started_at.type.timezone is True
    assert columns.completed_at.type.timezone is True


def test_job_defaults_are_callable_or_exact_and_json_is_unwrapped():
    columns = Job.__table__.columns
    assert callable(columns.job_id.default.arg)
    assert columns.job_id.server_default is None
    assert columns.status.default.arg is JobStatus.PENDING
    assert _normalized(columns.status.server_default.arg) == "'pending'"
    assert columns.version.default.arg == 0
    assert _normalized(columns.version.server_default.arg) == "0"
    assert callable(columns.payload_json.default.arg)
    assert columns.payload_json.default.arg(None) is not columns.payload_json.default.arg(
        None
    )
    assert _normalized(columns.payload_json.server_default.arg) == "'{}'::jsonb"
    assert columns.result_json.server_default is None
    assert columns.error.server_default is None
    assert columns.started_at.server_default is None
    assert columns.completed_at.server_default is None
    assert "Mutable" not in type(columns.payload_json.type).__name__


def test_job_foreign_keys_are_nullable_child_owned_cascades():
    foreign_keys = {fk.parent.name: fk for fk in Job.__table__.foreign_keys}
    assert set(foreign_keys) == {"user_id", "marketing_run_id"}
    assert foreign_keys["user_id"].target_fullname == "users.id"
    assert foreign_keys["user_id"].ondelete == "CASCADE"
    assert foreign_keys["marketing_run_id"].target_fullname == (
        "marketing_runs.run_id"
    )
    assert foreign_keys["marketing_run_id"].ondelete == "CASCADE"


def test_all_four_relationship_attributes_match_contract():
    job_relationships = inspect(Job).relationships
    user_relationship = job_relationships.user
    run_relationship = job_relationships.marketing_run
    user_jobs = inspect(User).relationships.jobs
    run_jobs = inspect(MarketingRun).relationships.jobs

    assert user_relationship.direction is MANYTOONE
    assert user_relationship.back_populates == "jobs"
    assert str(user_relationship.cascade) == "CascadeOptions('merge,save-update')"
    assert user_relationship.passive_deletes is False
    assert {column.name for column in user_relationship.local_columns} == {"user_id"}

    assert run_relationship.direction is MANYTOONE
    assert run_relationship.back_populates == "jobs"
    assert str(run_relationship.cascade) == "CascadeOptions('merge,save-update')"
    assert run_relationship.passive_deletes is False
    assert {column.name for column in run_relationship.local_columns} == {
        "marketing_run_id"
    }

    assert user_jobs.direction is ONETOMANY
    assert user_jobs.back_populates == "user"
    assert str(user_jobs.cascade) == (
        "CascadeOptions('delete,delete-orphan,expunge,merge,refresh-expire,save-update')"
    )
    assert user_jobs.passive_deletes is True

    assert run_jobs.direction is ONETOMANY
    assert run_jobs.back_populates == "marketing_run"
    assert str(run_jobs.cascade) == (
        "CascadeOptions('delete,delete-orphan,expunge,merge,refresh-expire,save-update')"
    )
    assert run_jobs.passive_deletes is True


def test_job_has_exact_named_checks_and_predicates():
    checks = {
        constraint.name: _normalized(constraint.sqltext)
        for constraint in Job.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert set(checks) == EXPECTED_CHECKS
    assert checks["ck_jobs_job_id_format"] == "job_id ~ '^[0-9a-f]{32}$'"
    assert checks["ck_jobs_kind_format"] == (
        "kind ~ '^[a-z][a-z0-9_.-]{0,63}$'"
    )
    assert checks["ck_jobs_workflow_step_format"] == (
        "workflow_step IS NULL OR workflow_step ~ '^[a-z][a-z0-9_.-]{0,63}$'"
    )
    assert checks["ck_jobs_exclusive_owner"] == (
        "marketing_run_id IS NULL OR user_id IS NULL"
    )
    assert checks["ck_jobs_step_requires_run"] == (
        "workflow_step IS NULL OR marketing_run_id IS NOT NULL"
    )
    assert checks["ck_jobs_status"] == (
        "status IN ('pending', 'running', 'succeeded', 'failed')"
    )
    assert checks["ck_jobs_version_nonnegative"] == "version >= 0"
    assert checks["ck_jobs_payload_object"] == (
        "jsonb_typeof(payload_json) = 'object'"
    )
    assert checks["ck_jobs_result_object"] == (
        "result_json IS NULL OR jsonb_typeof(result_json) = 'object'"
    )
    assert "btrim(error, E'\\x09\\x0A\\x0B\\x0C\\x0D\\x20') <> ''" in checks[
        "ck_jobs_lifecycle"
    ]
    assert "updated_at >= created_at" in checks["ck_jobs_timestamp_order"]
    assert "status = 'running' AND updated_at = started_at" in checks[
        "ck_jobs_timestamp_order"
    ]


def test_job_has_only_approved_secondary_indexes():
    indexes = {index.name: tuple(column.name for column in index.columns) for index in Job.__table__.indexes}
    assert indexes == {
        "ix_jobs_run_created_job": (
            "marketing_run_id",
            "created_at",
            "job_id",
        ),
        "ix_jobs_status_created_job": ("status", "created_at", "job_id"),
    }


class _OperationRecorder:
    def __init__(self) -> None:
        self.operations: list[tuple[str, object]] = []

    def create_table(self, name, *objects):
        self.operations.append(("create_table", (name, objects)))

    def create_index(self, name, table_name, columns, unique=False):
        self.operations.append(
            ("create_index", (name, table_name, tuple(columns), unique))
        )

    def drop_index(self, name, table_name):
        self.operations.append(("drop_index", (name, table_name)))

    def drop_table(self, name):
        self.operations.append(("drop_table", name))


def _load_job_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260825_0004_durable_job_persistence.py"
    )
    spec = importlib.util.spec_from_file_location("job_migration_0004", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_exact_parent_upgrade_and_downgrade_operations():
    migration = _load_job_migration()
    assert migration.revision == "20260825_0004"
    assert migration.down_revision == "20260814_0003"

    recorder = _OperationRecorder()
    migration.op = recorder
    migration.upgrade()

    assert [operation[0] for operation in recorder.operations] == [
        "create_table",
        "create_index",
        "create_index",
    ]
    table_name, objects = recorder.operations[0][1]
    assert table_name == "jobs"
    columns = tuple(obj.name for obj in objects if hasattr(obj, "type"))
    assert columns == EXPECTED_COLUMNS
    checks = {
        obj.name for obj in objects if isinstance(obj, CheckConstraint)
    }
    assert checks == EXPECTED_CHECKS
    foreign_keys = [obj for obj in objects if isinstance(obj, ForeignKeyConstraint)]
    assert len(foreign_keys) == 2
    assert all(foreign_key.ondelete == "CASCADE" for foreign_key in foreign_keys)
    assert recorder.operations[1][1] == (
        "ix_jobs_run_created_job",
        "jobs",
        ("marketing_run_id", "created_at", "job_id"),
        False,
    )
    assert recorder.operations[2][1] == (
        "ix_jobs_status_created_job",
        "jobs",
        ("status", "created_at", "job_id"),
        False,
    )

    recorder.operations.clear()
    migration.downgrade()
    assert recorder.operations == [
        ("drop_index", ("ix_jobs_status_created_job", "jobs")),
        ("drop_index", ("ix_jobs_run_created_job", "jobs")),
        ("drop_table", "jobs"),
    ]
