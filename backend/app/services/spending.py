"""Deterministic policy and legal state transitions; no payments are executed.

Every call must run inside spending_service(). SQLite's database-wide write lock
is acquired BEFORE any read and held through commit. This works across threads
and processes sharing the same SQLite file (not just a Python mutex).
"""
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.spending import Permit, PermitCategory, PermitMerchant, PurchaseRequest, utcnow
from app.schemas.spending import PermitCreate, PermitOut, PurchaseCreate, PurchaseOut, SpendingSummary


class DomainError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@contextmanager
def spending_service(engine):
    if engine.dialect.name != 'sqlite':
        raise DomainError(503, 'Authorization serialization currently requires SQLite')
    with Session(engine, expire_on_commit=False) as session:
        try:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            yield SpendingService(session)
            session.commit()
        except BaseException:
            session.rollback()
            raise


class SpendingService:
    def __init__(self, session: Session):
        self.session = session

    def permit(self, permit_id: str, owner_id: str | None = None) -> Permit:
        permit = self.session.get(Permit, permit_id)
        if permit is None or (owner_id is not None and permit.owner_id != owner_id):
            raise DomainError(404, 'Permit not found')
        return permit

    def purchase(self, request_id: str) -> PurchaseRequest:
        purchase = self.session.get(PurchaseRequest, request_id)
        if purchase is None:
            raise DomainError(404, 'Purchase request not found')
        return purchase

    def summary(self, permit: Permit) -> SpendingSummary:
        rows = self.session.execute(select(PurchaseRequest.state, PurchaseRequest.amount_cents).where(
            PurchaseRequest.permit_id == permit.id,
            PurchaseRequest.state.in_(['authorized', 'fulfilled']),
        )).all()
        spent = sum(amount for state, amount in rows if state == 'fulfilled')
        reserved = sum(amount for state, amount in rows if state == 'authorized')
        return SpendingSummary(fulfilled_spend_cents=spent, active_reservations_cents=reserved,
                               remaining_cents=permit.total_limit_cents - spent - reserved)

    def permit_output(self, permit: Permit) -> PermitOut:
        fields = {field: getattr(permit, field) for field in PermitOut.model_fields if field != 'spending'}
        return PermitOut(**fields, spending=self.summary(permit))

    def create_permit(self, data: PermitCreate, owner_id: str) -> PermitOut:
        fields = data.model_dump(exclude={'allowed_merchants', 'allowed_categories'})
        permit = Permit(**fields, owner_id=owner_id,
                        merchants=[PermitMerchant(identifier=value) for value in data.allowed_merchants],
                        categories=[PermitCategory(identifier=value) for value in data.allowed_categories])
        self.session.add(permit)
        self.session.flush()
        return self.permit_output(permit)

    def list_permits(self, owner_id: str):
        permits = self.session.scalars(select(Permit).where(Permit.owner_id == owner_id).order_by(Permit.created_at, Permit.id))
        return [self.permit_output(permit) for permit in permits]

    def policy_denial(self, permit: Permit, purchase: PurchaseRequest) -> str | None:
        # Stable ordering gives deterministic reasons when multiple rules fail.
        if permit.status != 'active':
            return 'permit_revoked'
        if permit.expires_at <= utcnow():
            return 'permit_expired'
        if purchase.agent_id != permit.agent_id:
            return 'agent_mismatch'
        if purchase.currency != 'USD' or purchase.currency != permit.currency:
            return 'unsupported_currency'
        if purchase.amount_cents <= 0:
            return 'invalid_amount'
        if purchase.merchant not in permit.allowed_merchants:
            return 'merchant_not_allowed'
        if purchase.category not in permit.allowed_categories:
            return 'category_not_allowed'
        if purchase.amount_cents > permit.per_purchase_limit_cents:
            return 'per_purchase_limit_exceeded'
        if purchase.amount_cents > self.summary(permit).remaining_cents:
            return 'insufficient_budget'
        return None

    def submit(self, data: PurchaseCreate, authenticated_agent: str) -> PurchaseOut:
        if data.agent_id != authenticated_agent:
            raise DomainError(403, 'Agent identity does not match credential')
        fields = data.model_dump(mode='json')
        existing = self.session.scalar(select(PurchaseRequest).where(
            PurchaseRequest.agent_id == data.agent_id,
            PurchaseRequest.external_request_id == data.external_request_id,
        ))
        if existing:
            if any(getattr(existing, key) != value for key, value in fields.items()):
                raise DomainError(409, 'Idempotency key already used with different details')
            return PurchaseOut.model_validate(existing)
        permit = self.permit(str(data.permit_id))
        purchase = PurchaseRequest(**fields)
        denial = self.policy_denial(permit, purchase)
        purchase.denial_reason = denial
        if denial:
            purchase.state = 'denied'
        elif permit.approval_threshold_cents is not None and purchase.amount_cents > permit.approval_threshold_cents:
            purchase.state = 'pending_approval'
        else:
            purchase.state = 'authorized'
        self.session.add(purchase)
        self.session.flush()
        return PurchaseOut.model_validate(purchase)

    def visible_purchase(self, request_id: str, role: str, subject: str) -> PurchaseRequest:
        purchase = self.purchase(request_id)
        permit = self.permit(purchase.permit_id)
        if (role == 'owner' and permit.owner_id == subject) or (role == 'agent' and purchase.agent_id == subject):
            return purchase
        raise DomainError(404, 'Purchase request not found')

    def transition(self, purchase: PurchaseRequest, eligible: set[str], state: str, reason: str | None = None):
        if purchase.state not in eligible:
            raise DomainError(409, f'Cannot transition {purchase.state} to {state}')
        purchase.state = state
        purchase.denial_reason = reason
        purchase.updated_at = utcnow()
        self.session.flush()
        return PurchaseOut.model_validate(purchase)

    def approve(self, request_id: str, owner_id: str):
        purchase = self.visible_purchase(request_id, 'owner', owner_id)
        if purchase.state != 'pending_approval':
            raise DomainError(409, 'Only pending requests can be approved')
        denial = self.policy_denial(self.permit(purchase.permit_id), purchase)
        return self.transition(purchase, {'pending_approval'}, 'denied' if denial else 'authorized', denial)

    def reject(self, request_id: str, owner_id: str):
        purchase = self.visible_purchase(request_id, 'owner', owner_id)
        return self.transition(purchase, {'pending_approval'}, 'rejected', 'owner_rejected')

    def cancel(self, request_id: str, role: str, subject: str):
        purchase = self.visible_purchase(request_id, role, subject)
        return self.transition(purchase, {'pending_approval', 'authorized'}, 'cancelled', 'cancelled')

    def revoke(self, permit_id: str, owner_id: str):
        permit = self.permit(permit_id, owner_id)
        permit.status = 'revoked'
        purchases = self.session.scalars(select(PurchaseRequest).where(
            PurchaseRequest.permit_id == permit_id,
            PurchaseRequest.state.in_(['pending_approval', 'authorized']),
        )).all()
        for purchase in purchases:
            self.transition(purchase, {'pending_approval', 'authorized'}, 'cancelled', 'permit_revoked')
        self.session.flush()
        return self.permit_output(permit)

    # Internal trusted settlement transitions ONLY. No HTTP routes expose these.
    def mark_fulfilled(self, request_id: str):
        return self.transition(self.purchase(request_id), {'authorized'}, 'fulfilled')

    def mark_failed(self, request_id: str):
        return self.transition(self.purchase(request_id), {'authorized'}, 'failed', 'fulfillment_failed')
