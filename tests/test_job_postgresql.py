from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job, JobStatus, MarketingRun, User
from app.services.job_persistence_service import (
    IllegalJobTransitionError,
    JobPersistenceService,
    StaleJobVersionError,
)


DATABASE_ENV = "DURABLE_JOB_TEST_DATABASE_URL"
RAW_DATABASE_URL = os.getenv(DATABASE_ENV)
pytestmark = pytest.mark.skipif(
    not RAW_DATABASE_URL,
    reason=(
        f"{DATABASE_ENV} is not configured; PostgreSQL-only durable Job "
        "evidence requires an explicitly disposable database"
    ),
)

REVISION = "20260825_0004"
PARENT = "20260814_0003"
SEED_USER_ID = 2_147_483_000
SEED_RUN_ID = "durable-job-migration-seed"
SEED_ARTIFACT_KEY = "durable-job-migration-seed"
CREATED = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)


def sync_url(raw_url):
    return raw_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


def async_url(raw_url):
    if raw_url.startswith("postgresql+asyncpg://"):
        return raw_url
    if raw_url.startswith("postgresql+psycopg2://"):
        return raw_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)


def current_revision(engine):
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return None
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if len(rows) > 1:
        pytest.fail(f"disposable PostgreSQL target has multiple heads: {rows}")
    return rows[0] if rows else None


@dataclass
class PostgresEvidenceDatabase:
    engine: object
    config: Config
    raw_url: str


@pytest.fixture(scope="module")
def postgres_database():
    raw_url = RAW_DATABASE_URL
    parsed = make_url(sync_url(raw_url))
    database_name = parsed.database or ""
    if "durable_job_test" not in database_name.lower():
        pytest.fail(
            f"{DATABASE_ENV} database name must contain 'durable_job_test'; "
            f"refusing destructive migration evidence against {database_name!r}"
        )

    previous_settings_url = settings.DATABASE_URL
    settings.DATABASE_URL = raw_url
    engine = create_engine(sync_url(raw_url))
    config = Config("alembic.ini")
    starting_revision = current_revision(engine)
    known_revisions = {None, "20260801_0001", "20260808_0002", PARENT, REVISION}
    if starting_revision not in known_revisions:
        pytest.fail(
            f"unsupported starting revision in disposable database: {starting_revision}"
        )

    try:
        if starting_revision == REVISION:
            command.downgrade(config, PARENT)
        elif starting_revision != PARENT:
            command.upgrade(config, PARENT)

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (id, telegram_id, username)
                    VALUES (:id, :telegram_id, :username)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": SEED_USER_ID,
                    "telegram_id": 9_223_372_036_000_000_000,
                    "username": "durable-job-migration-seed",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO marketing_runs (
                        run_id, user_id, workflow_type, status, input_json, state_json
                    ) VALUES (
                        :run_id, :user_id, 'migration_evidence', 'created',
                        CAST('{}' AS jsonb), CAST('{}' AS jsonb)
                    ) ON CONFLICT (run_id) DO NOTHING
                    """
                ),
                {"run_id": SEED_RUN_ID, "user_id": SEED_USER_ID},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO marketing_artifacts (
                        run_id, artifact_key, artifact_type, payload_json
                    ) VALUES (
                        :run_id, :artifact_key, 'migration_evidence',
                        CAST('{}' AS jsonb)
                    ) ON CONFLICT ON CONSTRAINT uq_marketing_artifacts_run_key
                    DO NOTHING
                    """
                ),
                {"run_id": SEED_RUN_ID, "artifact_key": SEED_ARTIFACT_KEY},
            )

        command.upgrade(config, REVISION)
        yield PostgresEvidenceDatabase(engine=engine, config=config, raw_url=raw_url)
    finally:
        try:
            if current_revision(engine) != PARENT:
                command.downgrade(config, PARENT)
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM marketing_runs WHERE run_id = :run_id"),
                    {"run_id": SEED_RUN_ID},
                )
                connection.execute(
                    text("DELETE FROM users WHERE id = :user_id"),
                    {"user_id": SEED_USER_ID},
                )
            if starting_revision == REVISION:
                command.upgrade(config, REVISION)
            elif starting_revision != PARENT:
                command.downgrade(config, starting_revision or "base")
        finally:
            engine.dispose()
            settings.DATABASE_URL = previous_settings_url


def schema_signature(engine):
    inspector = inspect(engine)
    columns = [
        (
            column["name"],
            str(column["type"]),
            column["nullable"],
            str(column.get("default")),
        )
        for column in inspector.get_columns("jobs")
    ]
    checks = sorted(
        (constraint["name"], " ".join(constraint["sqltext"].split()))
        for constraint in inspector.get_check_constraints("jobs")
    )
    indexes = sorted(
        (index["name"], tuple(index["column_names"]), index["unique"])
        for index in inspector.get_indexes("jobs")
    )
    foreign_keys = sorted(
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            foreign_key["options"].get("ondelete"),
        )
        for foreign_key in inspector.get_foreign_keys("jobs")
    )
    return columns, checks, indexes, foreign_keys


def test_migration_upgrade_preserves_seed_and_reflects_exact_contract(
    postgres_database,
):
    engine = postgres_database.engine
    assert current_revision(engine) == REVISION
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM users WHERE id = :id"),
            {"id": SEED_USER_ID},
        ) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM marketing_runs WHERE run_id = :run_id"),
            {"run_id": SEED_RUN_ID},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM marketing_artifacts "
                "WHERE run_id = :run_id AND artifact_key = :key"
            ),
            {"run_id": SEED_RUN_ID, "key": SEED_ARTIFACT_KEY},
        ) == 1

    columns, checks, indexes, foreign_keys = schema_signature(engine)
    assert [column[0] for column in columns] == [
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
    ]
    assert {name for name, _predicate in checks} == {
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
    assert indexes == [
        ("ix_jobs_run_created_job", ("marketing_run_id", "created_at", "job_id"), False),
        ("ix_jobs_status_created_job", ("status", "created_at", "job_id"), False),
    ]
    assert foreign_keys == [
        (("marketing_run_id",), "marketing_runs", ("run_id",), "CASCADE"),
        (("user_id",), "users", ("id",), "CASCADE"),
    ]


def insert_job(engine, job_id, **overrides):
    values = {
        "job_id": job_id,
        "user_id": None,
        "marketing_run_id": None,
        "workflow_step": None,
        "kind": "valid.kind",
        "status": "pending",
        "version": 0,
        "payload_json": json.dumps({}),
        "result_json": None,
        "error": None,
        "created_at": CREATED,
        "updated_at": CREATED,
        "started_at": None,
        "completed_at": None,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO jobs (
                    job_id, user_id, marketing_run_id, workflow_step, kind,
                    status, version, payload_json, result_json, error,
                    created_at, updated_at, started_at, completed_at
                ) VALUES (
                    :job_id, :user_id, :marketing_run_id, :workflow_step, :kind,
                    :status, :version, CAST(:payload_json AS jsonb),
                    CAST(:result_json AS jsonb), :error,
                    :created_at, :updated_at, :started_at, :completed_at
                )
                """
            ),
            values,
        )


def assert_rejected(engine, ordinal, **overrides):
    job_id = f"{ordinal:032x}"
    with pytest.raises(IntegrityError):
        insert_job(engine, job_id, **overrides)


def test_each_postgresql_constraint_accepts_and_rejects_independently(
    postgres_database,
):
    engine = postgres_database.engine
    insert_job(engine, f"{1:032x}")
    insert_job(
        engine,
        f"{2:032x}",
        marketing_run_id=SEED_RUN_ID,
        workflow_step="valid.step",
    )
    insert_job(engine, f"{3:032x}", user_id=SEED_USER_ID)
    insert_job(
        engine,
        f"{4:032x}",
        status="running",
        started_at=CREATED + timedelta(seconds=1),
        updated_at=CREATED + timedelta(seconds=1),
    )
    insert_job(
        engine,
        f"{5:032x}",
        status="succeeded",
        started_at=CREATED + timedelta(seconds=1),
        completed_at=CREATED + timedelta(seconds=2),
        updated_at=CREATED + timedelta(seconds=2),
        result_json=json.dumps({}),
    )
    insert_job(
        engine,
        f"{6:032x}",
        status="failed",
        started_at=CREATED + timedelta(seconds=1),
        completed_at=CREATED + timedelta(seconds=2),
        updated_at=CREATED + timedelta(seconds=2),
        error="sanitized",
    )

    cases = [
        {"job_id": "A" * 32},
        {"kind": "Invalid"},
        {"marketing_run_id": SEED_RUN_ID, "workflow_step": "Invalid"},
        {"user_id": SEED_USER_ID, "marketing_run_id": SEED_RUN_ID},
        {"workflow_step": "valid.step"},
        {"status": "unknown"},
        {"version": -1},
        {"payload_json": json.dumps([])},
        {"result_json": json.dumps([])},
        {"status": "failed", "error": " \t\r\n"},
        {"status": "running", "started_at": CREATED - timedelta(seconds=1), "updated_at": CREATED - timedelta(seconds=1)},
    ]
    for ordinal, overrides in enumerate(cases, start=100):
        if "job_id" in overrides:
            with pytest.raises(IntegrityError):
                insert_job(engine, overrides.pop("job_id"), **overrides)
        else:
            assert_rejected(engine, ordinal, **overrides)


def test_migration_downgrade_and_deterministic_reupgrade(postgres_database):
    engine = postgres_database.engine
    config = postgres_database.config
    before = schema_signature(engine)
    command.downgrade(config, PARENT)
    assert current_revision(engine) == PARENT
    assert not inspect(engine).has_table("jobs")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM marketing_runs WHERE run_id = :run_id"),
            {"run_id": SEED_RUN_ID},
        ) == 1
    command.upgrade(config, REVISION)
    assert current_revision(engine) == REVISION
    assert schema_signature(engine) == before


def test_foreign_key_cascades_remove_owned_jobs(postgres_database):
    engine = postgres_database.engine
    user_job_id = f"{200:032x}"
    run_job_id = f"{201:032x}"
    insert_job(engine, user_job_id, user_id=SEED_USER_ID)
    insert_job(engine, run_job_id, marketing_run_id=SEED_RUN_ID)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM marketing_runs WHERE run_id = :run_id"),
            {"run_id": SEED_RUN_ID},
        )
        assert connection.scalar(
            text("SELECT count(*) FROM jobs WHERE job_id = :job_id"),
            {"job_id": run_job_id},
        ) == 0
        connection.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": SEED_USER_ID},
        )
        assert connection.scalar(
            text("SELECT count(*) FROM jobs WHERE job_id = :job_id"),
            {"job_id": user_job_id},
        ) == 0


@pytest.mark.parametrize("owner_kind", ["user", "run"])
@pytest.mark.parametrize("loaded", [False, True])
def test_loaded_and_unloaded_orm_owner_deletion_never_nullifies_job_owner(
    postgres_database, owner_kind, loaded
):
    engine = postgres_database.engine
    ordinal = 220 + (10 if owner_kind == "run" else 0) + int(loaded)
    job_id = f"{ordinal:032x}"
    user_id = SEED_USER_ID - ordinal
    run_id = f"durable-job-owner-{ordinal}"
    with engine.begin() as connection:
        if owner_kind == "user":
            connection.execute(
                text(
                    "INSERT INTO users (id, telegram_id, username) "
                    "VALUES (:id, :telegram_id, 'job-owner-evidence')"
                ),
                {"id": user_id, "telegram_id": 8_000_000_000_000_000_000 + ordinal},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO marketing_runs (run_id, workflow_type, status) "
                    "VALUES (:run_id, 'evidence', 'created')"
                ),
                {"run_id": run_id},
            )
    insert_job(
        engine,
        job_id,
        user_id=user_id if owner_kind == "user" else None,
        marketing_run_id=run_id if owner_kind == "run" else None,
    )

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as session:
            owner = (
                session.get(User, user_id)
                if owner_kind == "user"
                else session.get(MarketingRun, run_id)
            )
            if loaded:
                assert [job.job_id for job in owner.jobs] == [job_id]
            session.delete(owner)
            session.commit()
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert not any(statement.lstrip().upper().startswith("UPDATE JOBS") for statement in statements)
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        ) == 0


@pytest.mark.parametrize("owner_kind", ["user", "run"])
def test_loaded_owner_collection_removal_uses_delete_orphan(
    postgres_database, owner_kind
):
    engine = postgres_database.engine
    ordinal = 250 + int(owner_kind == "run")
    job_id = f"{ordinal:032x}"
    user_id = SEED_USER_ID - ordinal
    run_id = f"durable-job-removal-{ordinal}"
    with engine.begin() as connection:
        if owner_kind == "user":
            connection.execute(
                text(
                    "INSERT INTO users (id, telegram_id, username) "
                    "VALUES (:id, :telegram_id, 'job-removal-evidence')"
                ),
                {"id": user_id, "telegram_id": 8_100_000_000_000_000_000 + ordinal},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO marketing_runs (run_id, workflow_type, status) "
                    "VALUES (:run_id, 'evidence', 'created')"
                ),
                {"run_id": run_id},
            )
    insert_job(
        engine,
        job_id,
        user_id=user_id if owner_kind == "user" else None,
        marketing_run_id=run_id if owner_kind == "run" else None,
    )
    with Session(engine) as session:
        owner = (
            session.get(User, user_id)
            if owner_kind == "user"
            else session.get(MarketingRun, run_id)
        )
        target = next(job for job in owner.jobs if job.job_id == job_id)
        owner.jobs.remove(target)
        session.commit()
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        ) == 0


def test_row_lock_plus_expected_version_allows_one_same_snapshot_winner(
    postgres_database,
):
    job_id = f"{300:032x}"
    insert_job(postgres_database.engine, job_id)

    async def contend():
        engine = create_async_engine(async_url(postgres_database.raw_url))
        try:
            first = AsyncSession(engine, expire_on_commit=False)
            second = AsyncSession(engine, expire_on_commit=False)
            service = JobPersistenceService(
                lambda: CREATED + timedelta(seconds=1)
            )
            try:
                await first.begin()
                await second.begin()
                winner = await service.transition_job(
                    first, job_id, 0, JobStatus.RUNNING
                )
                waiter = asyncio.create_task(
                    service.transition_job(second, job_id, 0, JobStatus.RUNNING)
                )
                await asyncio.sleep(0.05)
                await first.commit()
                with pytest.raises(StaleJobVersionError):
                    await waiter
                await second.rollback()
                return winner
            finally:
                await first.close()
                await second.close()
        finally:
            await engine.dispose()

    winner = asyncio.run(contend())
    assert winner.status is JobStatus.RUNNING and winner.version == 1


def test_competing_terminal_transitions_have_one_winner(postgres_database):
    job_id = f"{301:032x}"
    insert_job(
        postgres_database.engine,
        job_id,
        status="running",
        version=1,
        started_at=CREATED + timedelta(seconds=1),
        updated_at=CREATED + timedelta(seconds=1),
    )

    async def contend():
        engine = create_async_engine(async_url(postgres_database.raw_url))
        try:
            winner_session = AsyncSession(engine, expire_on_commit=False)
            waiter_session = AsyncSession(engine, expire_on_commit=False)
            service = JobPersistenceService(
                lambda: CREATED + timedelta(seconds=2)
            )
            try:
                await winner_session.begin()
                await waiter_session.begin()
                winner = await service.transition_job(
                    winner_session,
                    job_id,
                    1,
                    JobStatus.SUCCEEDED,
                    result_json={"winner": "success"},
                )
                waiter = asyncio.create_task(
                    service.transition_job(
                        waiter_session,
                        job_id,
                        1,
                        JobStatus.FAILED,
                        error="sanitized failure",
                    )
                )
                await asyncio.sleep(0.05)
                await winner_session.commit()
                with pytest.raises(StaleJobVersionError):
                    await waiter
                await waiter_session.rollback()
                return winner
            finally:
                await winner_session.close()
                await waiter_session.close()
        finally:
            await engine.dispose()

    winner = asyncio.run(contend())
    assert winner.status is JobStatus.SUCCEEDED
    assert winner.version == 2
    assert winner.result_json == {"winner": "success"}


def test_newly_observed_sequential_versions_and_terminal_repetition(
    postgres_database,
):
    job_id = f"{302:032x}"
    insert_job(postgres_database.engine, job_id)

    async def transition_sequence():
        engine = create_async_engine(async_url(postgres_database.raw_url))
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                running = await JobPersistenceService(
                    lambda: CREATED + timedelta(seconds=1)
                ).transition_job(session, job_id, 0, JobStatus.RUNNING)
                await session.commit()
                assert running.version == 1

                succeeded = await JobPersistenceService(
                    lambda: CREATED + timedelta(seconds=2)
                ).transition_job(
                    session,
                    job_id,
                    1,
                    JobStatus.SUCCEEDED,
                    result_json={},
                )
                await session.commit()
                assert succeeded.version == 2

                with pytest.raises(StaleJobVersionError):
                    await JobPersistenceService().transition_job(
                        session,
                        job_id,
                        1,
                        JobStatus.SUCCEEDED,
                        result_json={},
                    )
                await session.rollback()
                with pytest.raises(IllegalJobTransitionError):
                    await JobPersistenceService().transition_job(
                        session,
                        job_id,
                        2,
                        JobStatus.SUCCEEDED,
                        result_json={},
                    )
                await session.rollback()
                return succeeded
        finally:
            await engine.dispose()

    terminal = asyncio.run(transition_sequence())
    assert terminal.status is JobStatus.SUCCEEDED and terminal.version == 2
