from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


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
