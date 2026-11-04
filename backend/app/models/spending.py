"""Persistent policy and request records. Money is always integer cents."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware datetime required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Permit(Base):
    __tablename__ = "permits"
    __table_args__ = (
        CheckConstraint("total_limit_cents > 0 AND per_purchase_limit_cents > 0"),
        CheckConstraint("per_purchase_limit_cents <= total_limit_cents"),
        CheckConstraint("approval_threshold_cents IS NULL OR approval_threshold_cents >= 0"),
        CheckConstraint("currency = 'USD'"),
        CheckConstraint("status IN ('active', 'revoked')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str]
    agent_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    currency: Mapped[str]
    total_limit_cents: Mapped[int]
    per_purchase_limit_cents: Mapped[int]
    approval_threshold_cents: Mapped[int | None]
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    merchants: Mapped[list['PermitMerchant']] = relationship(cascade="all, delete-orphan", lazy="selectin")
    categories: Mapped[list['PermitCategory']] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def allowed_merchants(self):
        return sorted(item.identifier for item in self.merchants)

    @property
    def allowed_categories(self):
        return sorted(item.identifier for item in self.categories)


class PermitMerchant(Base):
    __tablename__ = "permit_merchants"
    permit_id: Mapped[str] = mapped_column(ForeignKey("permits.id"), primary_key=True)
    identifier: Mapped[str] = mapped_column(primary_key=True)


class PermitCategory(Base):
    __tablename__ = "permit_categories"
    permit_id: Mapped[str] = mapped_column(ForeignKey("permits.id"), primary_key=True)
    identifier: Mapped[str] = mapped_column(primary_key=True)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (
        UniqueConstraint("agent_id", "external_request_id"),
        CheckConstraint("state IN ('pending_approval','authorized','denied','rejected','cancelled','fulfilled','failed')"),
        CheckConstraint("state NOT IN ('authorized', 'fulfilled') OR (amount_cents > 0 AND currency = 'USD')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    permit_id: Mapped[str] = mapped_column(ForeignKey("permits.id"), index=True)
    agent_id: Mapped[str]
    merchant: Mapped[str]
    category: Mapped[str]
    product_id: Mapped[str]
    currency: Mapped[str]
    amount_cents: Mapped[int]
    external_request_id: Mapped[str]
    state: Mapped[str]
    denial_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
