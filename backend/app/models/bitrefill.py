"""Additive tables: no credentials, recipient values, payment links or codes."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.spending import UTCDateTime, utcnow


class PurchasePreview(Base):
    __tablename__ = 'bitrefill_purchase_previews'
    __table_args__ = (CheckConstraint("state IN ('ready', 'blocked')"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    purchase_request_id: Mapped[str] = mapped_column(ForeignKey('purchase_requests.id'), index=True)
    product_snapshot: Mapped[dict] = mapped_column(JSON)
    denomination: Mapped[str]
    amount_cents: Mapped[int | None]
    currency: Mapped[str | None]
    payment_method: Mapped[str | None]
    recipient_digest: Mapped[str | None]  # keyed HMAC; never the recipient itself
    recipient_required: Mapped[bool]
    state: Mapped[str]
    blocker: Mapped[str | None]
    fingerprint: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PurchaseExecution(Base):
    __tablename__ = 'bitrefill_purchase_executions'
    __table_args__ = (CheckConstraint("state IN ('initiating','reconciliation_required','invoice_created','awaiting_payment','paid','delivered','failed')"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    purchase_request_id: Mapped[str] = mapped_column(ForeignKey('purchase_requests.id'), unique=True)
    preview_id: Mapped[str] = mapped_column(ForeignKey('bitrefill_purchase_previews.id'), unique=True)
    external_invoice_id: Mapped[str | None] = mapped_column(unique=True)
    state: Mapped[str]
    payment_status: Mapped[str] = mapped_column(default='unknown')
    delivery_status: Mapped[str] = mapped_column(default='unknown')
    error_code: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
