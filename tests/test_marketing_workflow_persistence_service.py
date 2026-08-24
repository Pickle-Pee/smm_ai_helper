import asyncio

from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql

from app.models import MarketingArtifact, MarketingRun
from app.services.marketing_workflow_persistence_service import (
    MarketingWorkflowPersistenceService,
)


class FakeScalarCollection:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class FakeExecuteResult:
    def __init__(self, *, scalar=None, scalars=None):
        self.scalar = scalar
        self.scalar_values = scalars or []

    def scalar_one_or_none(self):
        return self.scalar

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return FakeScalarCollection(self.scalar_values)


class FakeDbSession:
    def __init__(self, execute_results=None):
        self.execute_results = list(execute_results or [])
        self.executed = []
        self.added = []
        self.flushes = 0
        self.commits = 0

    async def execute(self, statement):
        self.executed.append(statement)
        if not self.execute_results:
            raise AssertionError("Unexpected execute call")
        return self.execute_results.pop(0)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


def test_create_user_owned_run_flushes_without_commit():
    db_session = FakeDbSession()

    run = asyncio.run(
        MarketingWorkflowPersistenceService.create_run(
            db_session,
            workflow_type="competitor_to_creative_to_mentor",
            input_json={"competitor_url": "https://example.com"},
            user_id=42,
            run_id="run-1",
        )
    )

    assert db_session.added == [run]
    assert db_session.flushes == 1
    assert db_session.commits == 0
    assert run.run_id == "run-1"
    assert run.user_id == 42
    assert run.workflow_type == "competitor_to_creative_to_mentor"
    assert run.status == "created"
    assert run.input_json == {"competitor_url": "https://example.com"}


def test_create_anonymous_run_generates_stable_identifier():
    db_session = FakeDbSession()

    run = asyncio.run(
        MarketingWorkflowPersistenceService.create_run(
            db_session,
            workflow_type="competitor_to_creative_to_mentor",
        )
    )

    assert isinstance(run.run_id, str)
    assert len(run.run_id) == 32
    assert run.user_id is None
    assert db_session.flushes == 1
    assert db_session.commits == 0


def test_get_run_returns_persisted_run():
    run = MarketingRun(run_id="run-1", workflow_type="mvp", status="running")
    db_session = FakeDbSession(
        [FakeExecuteResult(scalar=run)]
    )

    result = asyncio.run(
        MarketingWorkflowPersistenceService.get_run(db_session, "run-1")
    )

    assert result is run
    assert len(db_session.executed) == 1


def test_update_run_persists_lifecycle_fields_without_commit(monkeypatch):
    run = MarketingRun(
        run_id="run-1",
        workflow_type="mvp",
        status="created",
        input_json={"seed": True},
    )
    db_session = FakeDbSession()

    async def fake_get_run(_session, run_id):
        assert _session is db_session
        assert run_id == "run-1"
        return run

    monkeypatch.setattr(
        MarketingWorkflowPersistenceService,
        "get_run",
        staticmethod(fake_get_run),
    )

    result = asyncio.run(
        MarketingWorkflowPersistenceService.update_run(
            db_session,
            "run-1",
            status="failed",
            current_step="competitor_analysis",
            state_json={"attempt": 2},
            error="upstream unavailable",
        )
    )

    assert result is run
    assert run.status == "failed"
    assert run.current_step == "competitor_analysis"
    assert run.state_json == {"attempt": 2}
    assert run.error == "upstream unavailable"
    assert run.input_json == {"seed": True}
    assert run.updated_at is not None
    assert db_session.flushes == 1
    assert db_session.commits == 0


def test_update_unknown_run_raises(monkeypatch):
    async def fake_get_run(_session, _run_id):
        return None

    monkeypatch.setattr(
        MarketingWorkflowPersistenceService,
        "get_run",
        staticmethod(fake_get_run),
    )

    try:
        asyncio.run(
            MarketingWorkflowPersistenceService.update_run(
                FakeDbSession(),
                "missing",
                status="running",
            )
        )
    except ValueError as exc:
        assert str(exc) == "Unknown marketing run"
    else:
        raise AssertionError("Expected ValueError")


def test_upsert_artifact_uses_conflict_update_and_no_commit():
    artifact = MarketingArtifact(
        id=7,
        run_id="run-1",
        artifact_key="competitor_analysis",
        artifact_type="competitor_analysis",
        step="competitor_analysis",
        payload_json={"strengths": ["clear offer"]},
    )
    db_session = FakeDbSession(
        [FakeExecuteResult(scalar=artifact)]
    )

    result = asyncio.run(
        MarketingWorkflowPersistenceService.upsert_artifact(
            db_session,
            run_id="run-1",
            artifact_key="competitor_analysis",
            artifact_type="competitor_analysis",
            step="competitor_analysis",
            payload_json={"strengths": ["clear offer"]},
        )
    )

    assert result is artifact
    assert db_session.flushes == 1
    assert db_session.commits == 0

    sql = str(
        db_session.executed[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )
    assert "ON CONFLICT ON CONSTRAINT uq_marketing_artifacts_run_key DO UPDATE" in sql


def test_get_artifact_returns_named_artifact():
    artifact = MarketingArtifact(
        id=1,
        run_id="run-1",
        artifact_key="creative_package",
        artifact_type="creative_package",
        payload_json={"headline": "Test"},
    )
    db_session = FakeDbSession(
        [FakeExecuteResult(scalar=artifact)]
    )

    result = asyncio.run(
        MarketingWorkflowPersistenceService.get_artifact(
            db_session,
            "run-1",
            "creative_package",
        )
    )

    assert result is artifact


def test_list_artifacts_uses_deterministic_id_order():
    artifacts = [
        MarketingArtifact(
            id=1,
            run_id="run-1",
            artifact_key="a",
            artifact_type="competitor_analysis",
            payload_json={},
        ),
        MarketingArtifact(
            id=2,
            run_id="run-1",
            artifact_key="b",
            artifact_type="creative_package",
            payload_json={},
        ),
    ]
    db_session = FakeDbSession(
        [FakeExecuteResult(scalars=artifacts)]
    )

    result = asyncio.run(
        MarketingWorkflowPersistenceService.list_artifacts(
            db_session,
            "run-1",
        )
    )

    assert result == artifacts
    sql = str(db_session.executed[0])
    assert "ORDER BY marketing_artifacts.id ASC" in sql


def test_marketing_artifact_schema_has_retry_and_cascade_invariants():
    constraints = [
        constraint
        for constraint in MarketingArtifact.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        {column.name for column in constraint.columns}
        == {"run_id", "artifact_key"}
        and constraint.name == "uq_marketing_artifacts_run_key"
        for constraint in constraints
    )

    run_id_fk = next(
        fk
        for fk in MarketingArtifact.__table__.foreign_keys
        if fk.parent.name == "run_id"
    )
    assert run_id_fk.ondelete == "CASCADE"
