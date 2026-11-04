"""Strict public inputs: callers cannot supply ownership or authorization state."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID
import re

from pydantic import BaseModel, ConfigDict, Field, StrictInt, AwareDatetime, field_validator, model_validator

Money = Annotated[StrictInt, Field(ge=1, le=10**12)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]


def normalize_identifier(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise ValueError("Use an exact identifier containing letters, digits, dots, underscores or hyphens")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PermitCreate(Input):
    agent_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    currency: Literal['USD'] = 'USD'
    total_limit_cents: Money
    per_purchase_limit_cents: Money
    allowed_merchants: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    allowed_categories: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    approval_threshold_cents: Annotated[StrictInt, Field(ge=0, le=10**12)] | None = None
    expires_at: AwareDatetime

    @field_validator('allowed_merchants', 'allowed_categories')
    @classmethod
    def normalize_lists(cls, values):
        return sorted(set(normalize_identifier(value) for value in values))

    @model_validator(mode='after')
    def validate_policy(self):
        if self.per_purchase_limit_cents > self.total_limit_cents:
            raise ValueError('Per-purchase limit cannot exceed total limit')
        self.expires_at = self.expires_at.astimezone(timezone.utc)
        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError('Permit expiry must be in the future')
        return self

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, json_schema_extra={'examples': [{
        'agent_id': 'shopping-agent', 'name': 'Office supplies', 'currency': 'USD',
        'total_limit_cents': 10000, 'per_purchase_limit_cents': 3000,
        'allowed_merchants': ['office-store'], 'allowed_categories': ['supplies'],
        'approval_threshold_cents': 1500, 'expires_at': '2030-01-01T00:00:00Z',
    }]})


class PurchaseCreate(Input):
    permit_id: UUID
    agent_id: Identifier
    merchant: Identifier
    category: Identifier
    product_id: Identifier
    amount_cents: Annotated[StrictInt, Field(ge=-(10**12), le=10**12)]
    currency: Annotated[str, Field(min_length=1, max_length=8)] = 'USD'
    external_request_id: Identifier

    @field_validator('merchant', 'category')
    @classmethod
    def normalize(cls, value):
        return normalize_identifier(value)

    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, json_schema_extra={'examples': [{
        'permit_id': '00000000-0000-0000-0000-000000000001', 'agent_id': 'shopping-agent',
        'merchant': 'office-store', 'category': 'supplies', 'product_id': 'paper',
        'amount_cents': 800, 'currency': 'USD', 'external_request_id': 'order-001',
    }]})


class SpendingSummary(BaseModel):
    fulfilled_spend_cents: int
    active_reservations_cents: int
    remaining_cents: int


class PermitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: str
    agent_id: str
    name: str
    currency: Literal['USD']
    total_limit_cents: int
    per_purchase_limit_cents: int
    allowed_merchants: list[str]
    allowed_categories: list[str]
    approval_threshold_cents: int | None
    expires_at: AwareDatetime
    status: Literal['active', 'revoked']
    created_at: AwareDatetime
    spending: SpendingSummary


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    permit_id: UUID
    agent_id: str
    merchant: str
    category: str
    product_id: str
    amount_cents: int
    currency: str
    external_request_id: str
    state: Literal['pending_approval', 'authorized', 'denied', 'rejected', 'cancelled', 'fulfilled', 'failed']
    denial_reason: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
