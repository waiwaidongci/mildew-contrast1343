from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.constants.enums import Review, Status
from src.utils.time import now

class Schedule(Base):
    __tablename__ = 'schedules'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON)
    recipient: Mapped[str] = mapped_column(String(100))
    next_at: Mapped[datetime] = mapped_column(index=True)
    repeat_daily: Mapped[bool]
    enabled: Mapped[bool] = mapped_column(default=True)
    author: Mapped[str] = mapped_column(String(64))

class Run(Base):
    __tablename__ = 'runs'
    __table_args__ = (UniqueConstraint('schedule_id', 'scheduled_at'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey('schedules.id'))
    scheduled_at: Mapped[datetime | None]
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default=Status.QUEUED, index=True)
    params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    export_file: Mapped[str | None] = mapped_column(String(100))
    review: Mapped[str] = mapped_column(String(20), default=Review.PENDING)
    review_note: Mapped[str | None] = mapped_column(String(500))
    decision: Mapped[str | None] = mapped_column(String(120))
    attempt: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None]
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]

class Delivery(Base):
    __tablename__ = 'deliveries'

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id'), unique=True)
    recipient: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now)


class MergeSession(Base):
    """一次离线筛查合并：冻结参与库房与筛查参数，并保存发布后的总榜。"""
    __tablename__ = 'merge_sessions'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    rooms: Mapped[list] = mapped_column(JSON)
    params: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default='awaiting', index=True)
    ledger: Mapped[dict | None] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    published_at: Mapped[datetime | None]


class MergePackage(Base):
    """库房当前已入账的计数包，每个库房只保留最新一个版本。"""
    __tablename__ = 'merge_packages'
    __table_args__ = (UniqueConstraint('session_id', 'room'), UniqueConstraint('session_id', 'checksum'))

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('merge_sessions.id'), index=True)
    room: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(120))
    version: Mapped[int]
    state: Mapped[str] = mapped_column(String(20))  # accepted | superseded | returned
    checksum: Mapped[str] = mapped_column(String(64))
    positive_count: Mapped[int]
    negative_count: Mapped[int]
    pattern_hits: Mapped[dict] = mapped_column(JSON)
    credentials: Mapped[list] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(default=now)


class MergeAttempt(Base):
    """每个到达的分包都留痕，用于识别重试、迟到和退回换包。"""
    __tablename__ = 'merge_attempts'

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('merge_sessions.id'), index=True)
    room: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(120))
    version: Mapped[int]
    checksum: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(20))  # accepted | duplicate | stale | replaced | rejected
    detail: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=now)
