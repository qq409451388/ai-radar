"""ORM models for ai-radar (SQLAlchemy 2.x typed style).

All timestamps are stored in UTC. Pages convert to local timezone for display.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_radar.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Topic(Base):
    __tablename__ = "topic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    children: Mapped[list["Topic"]] = relationship(
        "Topic", backref="parent", remote_side=[id], lazy="select"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Topic {self.id} {self.name}>"


class SourceConfig(Base):
    __tablename__ = "source_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # RSS / GITHUB_RELEASE
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    repository: Mapped[str] = mapped_column(String(256), default="", server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)
    default_topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    default_topic: Mapped[Topic | None] = relationship("Topic", lazy="select")
    items: Mapped[list["SourceItem"]] = relationship(
        back_populates="source_config", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("source_type", "url", name="uq_source_type_url"),)


class SourceItem(Base):
    __tablename__ = "source_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_config_id: Mapped[int] = mapped_column(
        ForeignKey("source_config.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", server_default="")
    url: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    author: Mapped[str] = mapped_column(String(256), default="", server_default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    raw_content: Mapped[str] = mapped_column(Text, default="", server_default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    analyze_status: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", index=True
    )  # PENDING / SUCCESS / FAILED / IGNORED
    analyze_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source_config: Mapped[SourceConfig] = relationship(back_populates="items")
    change_point_links: Mapped[list["ChangePointSource"]] = relationship(
        back_populates="source_item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_config_id", "external_id", name="uq_source_item_external"),
    )


class ChangePoint(Base):
    __tablename__ = "change_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    why_it_matters: Mapped[str] = mapped_column(Text, default="", server_default="")
    importance: Mapped[int] = mapped_column(Integer, default=1, server_default="1", index=True)  # 1/3/5
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="ACTIVE", server_default="ACTIVE", index=True
    )  # ACTIVE / DEPRECATED
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    topic: Mapped[Topic | None] = relationship("Topic", lazy="select")
    source_links: Mapped[list["ChangePointSource"]] = relationship(
        back_populates="change_point", cascade="all, delete-orphan"
    )
    coverages: Mapped[list["KnowledgeCoverage"]] = relationship(
        back_populates="change_point", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("event_key", name="uq_change_point_event_key"),)


class ChangePointSource(Base):
    __tablename__ = "change_point_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_point_id: Mapped[int] = mapped_column(
        ForeignKey("change_point.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_item_id: Mapped[int] = mapped_column(
        ForeignKey("source_item.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    change_point: Mapped[ChangePoint] = relationship(back_populates="source_links")
    source_item: Mapped[SourceItem] = relationship(back_populates="change_point_links")

    __table_args__ = (
        UniqueConstraint("change_point_id", "source_item_id", name="uq_cp_source"),
    )


class ProfileSourceFile(Base):
    __tablename__ = "profile_source_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    ref: Mapped[str] = mapped_column(String(64), default="main", server_default="main")
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    github_sha: Mapped[str] = mapped_column(String(64), default="", server_default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    extracted_content_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(
        String(16), default="FAILED", server_default="FAILED", index=True
    )  # SUCCESS / FAILED
    sync_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    extraction_status: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", index=True
    )  # PENDING / SUCCESS / FAILED
    extraction_error: Mapped[str] = mapped_column(Text, default="", server_default="")
    last_extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    facts: Mapped[list["ProfileFact"]] = relationship(
        back_populates="source_file", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("repository", "file_path", name="uq_profile_repo_path"),
    )


class ProfileFact(Base):
    __tablename__ = "profile_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("profile_source_file.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    fact_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="SET NULL"), nullable=True, index=True
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), default="DISCUSSION", server_default="DISCUSSION")
    source_heading: Mapped[str] = mapped_column(String(256), default="", server_default="")
    source_line_start: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source_line_end: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source_file: Mapped[ProfileSourceFile] = relationship(back_populates="facts")
    topic: Mapped[Topic | None] = relationship("Topic", lazy="select")

    __table_args__ = (
        UniqueConstraint("source_file_id", "fact_key", name="uq_profile_fact_key"),
    )


class KnowledgeCoverage(Base):
    __tablename__ = "knowledge_coverage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_point_id: Mapped[int] = mapped_column(
        ForeignKey("change_point.id", ondelete="CASCADE"), nullable=False, index=True
    )
    coverage_level: Mapped[str] = mapped_column(String(16), default="NONE", server_default="NONE")
    coverage_coefficient: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    rationale: Mapped[str] = mapped_column(Text, default="", server_default="")
    matched_fact_ids_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    assessed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    model_name: Mapped[str] = mapped_column(String(128), default="", server_default="")
    trigger_type: Mapped[str] = mapped_column(
        String(32), default="SCHEDULED", server_default="SCHEDULED"
    )
    assessment_fingerprint: Mapped[str] = mapped_column(
        String(64), default="", server_default="", index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    change_point: Mapped[ChangePoint] = relationship(back_populates="coverages")


class TopicSnapshot(Base):
    __tablename__ = "topic_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topic.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    score_delta: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    total_weight: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    covered_weight: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    recent_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    important_gap_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    practiced_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("topic_id", "snapshot_date", name="uq_topic_snapshot_date"),)


class JobLog(Base):
    __tablename__ = "job_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="RUNNING", server_default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PipelineRun(Base):
    """A user-triggered, multi-step pipeline that survives page navigation."""

    __tablename__ = "pipeline_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="QUEUED", server_default="QUEUED", index=True
    )
    current_step: Mapped[str] = mapped_column(String(64), default="", server_default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="PipelineStep.position",
    )


class PipelineStep(Base):
    """Persistent state for one connected step in a pipeline run."""

    __tablename__ = "pipeline_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", index=True
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    processed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    success_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[PipelineRun] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("run_id", "step_key", name="uq_pipeline_run_step"),
    )


class LlmResponseCache(Base):
    """Persistent structured-response cache keyed by exact prompt/model."""

    __tablename__ = "llm_response_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LlmUsageLog(Base):
    """Token usage ledger for cost visibility in the Automation page."""

    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    input_chars: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_chars: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
