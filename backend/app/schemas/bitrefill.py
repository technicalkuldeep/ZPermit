"""Whitelisted catalog output and internal quote contract (not a provider schema)."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from app.schemas.spending import Input, Money


class Denomination(BaseModel):
    package_value: str


class Product(BaseModel):
    id: str
    name: str | None = None
    product_type: str | None = None
    country: str | None = None
    currency: str | None = None
    denominations: list[Denomination] = Field(default_factory=list)
    denomination_range: dict[str, str] | None = None
    recipient_type: str | None = None
    requires_prepayment: bool = False
    # Unknown is intentional: face value does not establish checkout price.
    available: bool | None = None
    quoted_total_cents: int | None = None
    purchase_blocker: str | None = 'quote_contract_unverified'

    @property
    def merchant(self):
        # Explicit policy convention: product slug, not an inferred brand name.
        return self.id

    @property
    def category(self):
        return self.product_type


class Quote(BaseModel):
    """Internal integration contract. Never deserialize agent input into this type.

    The live adapter cannot produce this until final cost/fees/availability/expiry
    and payment currency fields are verified. Tests use normalized domain fixtures.
    """
    model_config = ConfigDict(frozen=True)
    product: Product
    denomination: str
    total_cents: Money
    currency: Literal['USD']
    payment_method: Literal['fiat_card']
    expires_at: datetime

    @field_validator('expires_at')
    @classmethod
    def aware_expiry(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Quote expiry must be timezone-aware')
        return value


class CreatedInvoice(BaseModel):
    invoice_id: Annotated[str, Field(min_length=1, max_length=128)]


class InvoiceObservation(BaseModel):
    invoice_id: str
    invoice_status: Literal['unpaid', 'payment_detected', 'payment_confirmed', 'pending', 'complete',
                            'blocked', 'denied', 'payment_error', 'unknown']
    order_statuses: list[Literal['created', 'payment_detected', 'processing', 'delivered', 'failed', 'refunded', 'unknown']]
    product_ids: list[str]


class PrepareInput(Input):
    purchase_request_id: UUID = Field(description='Existing ZPermit request visible to the caller')
    denomination: Annotated[str, Field(min_length=1, max_length=128, examples=['10', '1GB, 7 Days'])]
    recipient: SecretStr | None = None


class ConfirmInput(Input):
    preview_fingerprint: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    confirm: StrictBool
    recipient: SecretStr | None = None

    @field_validator('confirm')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit owner confirmation must be true')
        return value


class PreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    purchase_request_id: UUID
    product_snapshot: Product
    denomination: str
    amount_cents: int | None
    currency: str | None
    state: Literal['ready', 'blocked']
    blocker: str | None
    fingerprint: str
    recipient_required: bool
    created_at: datetime
    expires_at: datetime | None


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    purchase_request_id: UUID
    preview_id: UUID
    state: str
    external_invoice_id: str | None
    payment_status: str
    delivery_status: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
