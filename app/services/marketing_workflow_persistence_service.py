from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketingArtifact, MarketingRun


_UNSET = object()


class MarketingWorkflowPersistenceService:
    """Durable storage operations for multi-step marketing workflows.

    Transaction ownership belongs to the caller. Methods may flush pending
    changes but intentionally do not commit independently.
    """

    @staticmethod
    async def create_run(
        db_session: AsyncSession,
        workflow_type: str,
        input_json: Any | None = None,
        *,
        user_id: int | None = None,
        run_id: str | None = None,
        status: str = "created",
        current_step: str | None = None,
        state_json: Any | None = None,
    ) -> MarketingRun:
        run = MarketingRun(
            run_id=run_id or uuid.uuid4().hex,
            user_id=user_id,
            workflow_type=workflow_type,
            status=status,
            current_step=current_step,
            input_json=input_json,
            state_json=state_json,
        )
        db_session.add(run)
        await db_session.flush()
        return run

    @staticmethod
    async def get_run(
        db_session: AsyncSession,
        run_id: str,
    ) -> MarketingRun | None:
        result = await db_session.execute(
            select(MarketingRun).where(MarketingRun.run_id == run_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def update_run(
        cls,
        db_session: AsyncSession,
        run_id: str,
        *,
        status: str | object = _UNSET,
        current_step: str | None | object = _UNSET,
        state_json: Any | object = _UNSET,
        error: str | None | object = _UNSET,
    ) -> MarketingRun:
        run = await cls.get_run(db_session, run_id)
        if run is None:
            raise ValueError("Unknown marketing run")

        if status is not _UNSET:
            run.status = str(status)
        if current_step is not _UNSET:
            run.current_step = current_step  # type: ignore[assignment]
        if state_json is not _UNSET:
            run.state_json = state_json
        if error is not _UNSET:
            run.error = error  # type: ignore[assignment]

        run.updated_at = datetime.utcnow()
        await db_session.flush()
        return run

    @staticmethod
    async def upsert_artifact(
        db_session: AsyncSession,
        *,
        run_id: str,
        artifact_key: str,
        artifact_type: str,
        payload_json: Any,
        step: str | None = None,
    ) -> MarketingArtifact:
        now = datetime.utcnow()
        statement = (
            insert(MarketingArtifact)
            .values(
                run_id=run_id,
                artifact_key=artifact_key,
                artifact_type=artifact_type,
                step=step,
                payload_json=payload_json,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_marketing_artifacts_run_key",
                set_={
                    "artifact_type": artifact_type,
                    "step": step,
                    "payload_json": payload_json,
                    "updated_at": now,
                },
            )
            .returning(MarketingArtifact)
        )
        result = await db_session.execute(statement)
        artifact = result.scalar_one()
        await db_session.flush()
        return artifact

    @staticmethod
    async def get_artifact(
        db_session: AsyncSession,
        run_id: str,
        artifact_key: str,
    ) -> MarketingArtifact | None:
        result = await db_session.execute(
            select(MarketingArtifact).where(
                MarketingArtifact.run_id == run_id,
                MarketingArtifact.artifact_key == artifact_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_artifacts(
        db_session: AsyncSession,
        run_id: str,
    ) -> list[MarketingArtifact]:
        result = await db_session.execute(
            select(MarketingArtifact)
            .where(MarketingArtifact.run_id == run_id)
            .order_by(MarketingArtifact.id.asc())
        )
        return list(result.scalars().all())
