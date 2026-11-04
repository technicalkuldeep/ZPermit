"""Independent testnet payment records; never settle USD/Bitrefill purchases."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.spending import UTCDateTime, utcnow


class TestnetPayment(Base):
    __tablename__ = 'zcash_testnet_payments'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key'),
        CheckConstraint('amount_zatoshis > 0 AND amount_zatoshis <= 100000000'),
        CheckConstraint("state IN ('pending_approval','initiating','submitted','broadcast','not_broadcast','failed','uncertain')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str]
    request_key: Mapped[str]
    source: Mapped[str]
    destination: Mapped[str]
    account_id: Mapped[str]
    amount_zatoshis: Mapped[int]
    fingerprint: Mapped[str]
    state: Mapped[str] = mapped_column(default='pending_approval')
    operation_id: Mapped[str | None]
    txid: Mapped[str | None] = mapped_column(unique=True)
    confirmations: Mapped[int | None]
    transaction_status: Mapped[str | None]
    error_code: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
