from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.schemas.public_testnet import PublicObservationOut


class MobilePaymentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    destination: str = Field(min_length=1, max_length=1024)
    amount_zatoshis: StrictInt = Field(gt=0, le=100_000_000)
    memo: str | None = Field(default=None, max_length=512)

    @field_validator('memo')
    @classmethod
    def memo_bytes(cls, value):
        if value is not None:
            try:
                encoded = value.encode('utf-8')
            except UnicodeError:
                raise ValueError('Memo must be valid UTF-8 text') from None
            if len(encoded) > 512:
                raise ValueError('Memo must not exceed 512 UTF-8 bytes')
        return value


class MobilePaymentOut(BaseModel):
    id: str
    destination: str
    amount_zatoshis: int
    amount_taz: str
    memo: str | None
    payment_uri: str
    qr_path: str
    observation_id: str | None
    created_at: datetime
    network: Literal['test'] = 'test'
    state: Literal['prepared_for_external_wallet'] = 'prepared_for_external_wallet'
    signing_wallet: Literal['Zingo Mobile'] = 'Zingo Mobile'
    wallet_link_support: Literal['unverified_for_installed_version'] = 'unverified_for_installed_version'
    owner_wallet_review_required: Literal[True] = True
    backend_broadcast: Literal[False] = False
    private_payment_details_verified: Literal[False] = False
    fee_policy: Literal['review_wallet_calculated_fee_before_send'] = 'review_wallet_calculated_fee_before_send'


class MobileEvidenceOut(BaseModel):
    request_id: str
    observation: PublicObservationOut
    association: Literal['owner_reported'] = 'owner_reported'
    recipient_verified: Literal[False] = False
    amount_verified: Literal[False] = False
    memo_verified: Literal[False] = False
    sender_verified: Literal[False] = False
