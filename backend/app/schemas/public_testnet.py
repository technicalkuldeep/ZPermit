from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ObserveTransactionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    txid: str = Field(pattern=r'^[0-9a-f]{64}$')


class PublicAddressInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    address: str = Field(min_length=1, max_length=1024)


class PublicObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    txid: str
    origin: Literal['wallet_initiated_owner_report']
    evidence: dict
    last_check_succeeded: bool
    error_code: str | None
    created_at: datetime
    last_checked_at: datetime
    last_verified_at: datetime
