import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    desc,
    func,
)
from lunair.db.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    key_hash = Column(String(128), unique=True, index=True, nullable=False)
    name = Column(String(128), nullable=False)
    rpm_limit = Column(Integer, default=60, nullable=False)
    tpm_limit = Column(Integer, default=100000, nullable=False)
    monthly_budget_usd = Column(Float, default=50.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        Index("ix_requests_key_id_created_at_desc", "key_id", desc("created_at")),
        Index("ix_requests_provider_created_at_desc", "provider", desc("created_at")),
        Index("ix_requests_cache_hit", "cache_hit"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id = Column(String(64), primary_key=True, default=generate_uuid)
    created_at = Column(DateTime(timezone=True), primary_key=True, server_default=func.now(), nullable=False)
    key_id = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    provider = Column(String(64), nullable=False)
    tokens_in = Column(Integer, default=0, nullable=False)
    tokens_out = Column(Integer, default=0, nullable=False)
    reasoning_tokens = Column(Integer, default=0, nullable=False)
    cached_tokens = Column(Integer, default=0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    latency_ms = Column(Float, default=0.0, nullable=False)
    ttft_ms = Column(Float, nullable=True)
    fallback_from = Column(String(128), nullable=True)
    pii_redacted = Column(Boolean, default=False, nullable=False)
    injection_blocked = Column(Boolean, default=False, nullable=False)
    cache_hit = Column(Boolean, default=False, nullable=False)
    cache_similarity = Column(Float, nullable=True)
    gateway_mode = Column(String(32), default="go", nullable=False)
    finish_reason = Column(String(64), nullable=True)


class PIIEvent(Base):
    __tablename__ = "pii_events"
    __table_args__ = (
        Index("ix_pii_events_request_id", "request_id"),
    )

    id = Column(String(64), primary_key=True, default=generate_uuid)
    request_id = Column(String(64), nullable=False)
    pii_type = Column(String(64), nullable=False)
    placeholder = Column(String(64), nullable=False)
    location = Column(String(32), default="prompt", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InjectionEvent(Base):
    __tablename__ = "injection_events"
    __table_args__ = (
        Index("ix_injection_events_request_id", "request_id"),
    )

    id = Column(String(64), primary_key=True, default=generate_uuid)
    request_id = Column(String(64), nullable=False)
    risk_score = Column(Float, nullable=False)
    threats = Column(Text, nullable=False)
    action_taken = Column(String(32), default="blocked", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    provider = Column(String(64), index=True, nullable=False)
    balance_usd = Column(Float, nullable=True)
    lifetime_spend_usd = Column(Float, nullable=True)
    snapshot_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(String(64), primary_key=True, default=generate_uuid)
    key_id = Column(String(64), index=True, nullable=True)
    monthly_limit_usd = Column(Float, default=50.0, nullable=False)
    current_spend_usd = Column(Float, default=0.0, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
