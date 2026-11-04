from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    destination: str = Field(min_length=1, max_length=1024)
    amount_zatoshis: StrictInt = Field(gt=0, le=100_000_000)


class PaymentConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmation: Literal['SEND TESTNET TAZ WITH AUTOMATIC ZIP317 FEE']


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source: str
    destination: str
    amount_zatoshis: int
    fingerprint: str
    state: str
    operation_id: str | None
    txid: str | None
    confirmations: int | None
    transaction_status: str | None
    error_code: str | None
    created_at: datetime
    expires_at: datetime
    updated_at: datetime
    network: Literal['test'] = 'test'
    privacy_policy: Literal['FullPrivacy'] = 'FullPrivacy'
    fee_policy: Literal['automatic_zip317'] = 'automatic_zip317'
