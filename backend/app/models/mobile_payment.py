"""Immutable phone-wallet requests and owner-reported evidence associations.

Neither table authorizes, broadcasts, or settles a purchase.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.spending import UTCDateTime, utcnow


class MobilePaymentRequest(Base):
    __tablename__ = 'zcash_mobile_payment_requests'
    __table_args__ = (
        UniqueConstraint('owner_id', 'request_key'),
        CheckConstraint('amount_zatoshis > 0 AND amount_zatoshis <= 100000000'),
    )
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str]
    request_key: Mapped[str]
    destination: Mapped[str]
    amount_zatoshis: Mapped[int]
    memo: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MobilePaymentEvidence(Base):
    __tablename__ = 'zcash_mobile_payment_evidence'
    request_id: Mapped[str] = mapped_column(ForeignKey('zcash_mobile_payment_requests.id'), primary_key=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey('zcash_public_transaction_observations.id'), unique=True)
