"""Public evidence only. No foreign key or settlement link to USD purchases."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.spending import UTCDateTime, utcnow


class PublicTransactionObservation(Base):
    __tablename__ = 'zcash_public_transaction_observations'
    __table_args__ = (UniqueConstraint('owner_id', 'request_key'), UniqueConstraint('owner_id', 'txid'))
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str]
    request_key: Mapped[str]
    txid: Mapped[str]
    origin: Mapped[str] = mapped_column(default='wallet_initiated_owner_report')
    evidence: Mapped[dict] = mapped_column(JSON)
    last_check_succeeded: Mapped[bool] = mapped_column(default=True)
    error_code: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
