from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    tasks: Mapped[list[Task]] = relationship(back_populates="user")
    brand_profile: Mapped[BrandProfile | None] = relationship(
        back_populates="user",
        uselist=False,
    )
    marketing_runs: Mapped[list[MarketingRun]] = relationship(back_populates="user")
    jobs: Mapped[list[Job]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(50), index=True)
    task_description: Mapped[str] = mapped_column(Text)
    answers: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="done"
    )  # done / error / running
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    user: Mapped[User | None] = relationship(back_populates="tasks")


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        index=True,
    )
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    channels: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    extra_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped[User] = relationship(back_populates="brand_profile")


class MarketingRun(Base):
    __tablename__ = "marketing_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    workflow_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="created", index=True)
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    state_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped[User | None] = relationship(back_populates="marketing_runs")
    artifacts: Mapped[list[MarketingArtifact]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="marketing_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MarketingArtifact(Base):
    __tablename__ = "marketing_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "artifact_key",
            name="uq_marketing_artifacts_run_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("marketing_runs.run_id", ondelete="CASCADE"),
        index=True,
    )
    artifact_key: Mapped[str] = mapped_column(String(128))
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    run: Mapped[MarketingRun] = relationship(back_populates="artifacts")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "job_id ~ '^[0-9a-f]{32}$'",
            name="ck_jobs_job_id_format",
        ),
        CheckConstraint(
            "kind ~ '^[a-z][a-z0-9_.-]{0,63}$'",
            name="ck_jobs_kind_format",
        ),
        CheckConstraint(
            "workflow_step IS NULL "
            "OR workflow_step ~ '^[a-z][a-z0-9_.-]{0,63}$'",
            name="ck_jobs_workflow_step_format",
        ),
        CheckConstraint(
            "marketing_run_id IS NULL OR user_id IS NULL",
            name="ck_jobs_exclusive_owner",
        ),
        CheckConstraint(
            "workflow_step IS NULL OR marketing_run_id IS NOT NULL",
            name="ck_jobs_step_requires_run",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_jobs_version_nonnegative",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_jobs_payload_object",
        ),
        CheckConstraint(
            "result_json IS NULL OR jsonb_typeof(result_json) = 'object'",
            name="ck_jobs_result_object",
        ),
        CheckConstraint(
            r"""
            (
                status = 'pending'
                AND started_at IS NULL
                AND completed_at IS NULL
                AND result_json IS NULL
                AND error IS NULL
            )
            OR (
                status = 'running'
                AND started_at IS NOT NULL
                AND completed_at IS NULL
                AND result_json IS NULL
                AND error IS NULL
            )
            OR (
                status = 'succeeded'
                AND started_at IS NOT NULL
                AND completed_at IS NOT NULL
                AND result_json IS NOT NULL
                AND error IS NULL
            )
            OR (
                status = 'failed'
                AND started_at IS NOT NULL
                AND completed_at IS NOT NULL
                AND result_json IS NULL
                AND error IS NOT NULL
                AND btrim(error, E'\x09\x0A\x0B\x0C\x0D\x20') <> ''
            )
            """,
            name="ck_jobs_lifecycle",
        ),
        CheckConstraint(
            """
            updated_at >= created_at
            AND (started_at IS NULL OR started_at >= created_at)
            AND (
                completed_at IS NULL
                OR (
                    started_at IS NOT NULL
                    AND completed_at >= started_at
                )
            )
            AND (
                (status = 'pending' AND updated_at = created_at)
                OR (status = 'running' AND updated_at = started_at)
                OR (
                    status IN ('succeeded', 'failed')
                    AND updated_at = completed_at
                )
            )
            """,
            name="ck_jobs_timestamp_order",
        ),
        Index(
            "ix_jobs_run_created_job",
            "marketing_run_id",
            "created_at",
            "job_id",
        ),
        Index(
            "ix_jobs_status_created_job",
            "status",
            "created_at",
            "job_id",
        ),
    )

    job_id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid.uuid4().hex,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    marketing_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("marketing_runs.run_id", ondelete="CASCADE"),
        nullable=True,
    )
    workflow_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(
            JobStatus,
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda values: [value.value for value in values],
            length=32,
        ),
        nullable=False,
        default=JobStatus.PENDING,
        server_default=text("'pending'"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[User | None] = relationship(back_populates="jobs")
    marketing_run: Mapped[MarketingRun | None] = relationship(
        back_populates="jobs"
    )


class TaskSessionRecord(Base):
    __tablename__ = "task_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="anonymous")
    agent_type: Mapped[str] = mapped_column(String(50), index=True)
    task_description: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32), default="text")
    answers: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str] = mapped_column(String(64), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Conversation(Base):
    __tablename__ = "conversations"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("conversations.user_id"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class UrlCache(Base):
    __tablename__ = "url_cache"

    url: Mapped[str] = mapped_column(String(2048), primary_key=True)
    extracted_text_hash: Mapped[str] = mapped_column(String(128))
    summary_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
