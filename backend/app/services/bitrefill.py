"""Server-owned preparation, one-shot checkout boundary, and reconciliation.

Network I/O occurs outside SQLite transactions. The durable initiating record is
committed BEFORE a possible checkout; cancellation/revocation retain its funds.
"""
import hashlib
import hmac
import json
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.security import Identity
from app.integrations.bitrefill import ProviderError
from app.models.bitrefill import PurchaseExecution, PurchasePreview
from app.models.spending import utcnow
from app.schemas.bitrefill import ConfirmInput, ExecutionOut, PrepareInput, PreviewOut, Product, Quote
from app.services.spending import DomainError, spending_service


class BitrefillWorkflow:
    def __init__(self, engine, settings: Settings, provider):
        self.engine, self.settings, self.provider = engine, settings, provider

    def _execution(self, svc, execution_id, owner_id):
        execution = svc.session.get(PurchaseExecution, execution_id)
        if execution is None:
            raise DomainError(404, 'Execution not found')
        svc.visible_purchase(execution.purchase_request_id, 'owner', owner_id)
        return execution

    def _preview(self, svc, preview_id, identity):
        preview = svc.session.get(PurchasePreview, preview_id)
        if preview is None:
            raise DomainError(404, 'Preview not found')
        purchase = svc.visible_purchase(preview.purchase_request_id, identity.role, identity.subject)
        return preview, purchase

    def _no_execution(self, svc, request_id):
        if svc.session.scalar(select(PurchaseExecution.id).where(PurchaseExecution.purchase_request_id == request_id)):
            raise DomainError(409, 'An execution already exists; reconcile it instead of retrying checkout')

    def _recipient_digest(self, recipient):
        if recipient is None:
            return None
        key = self.settings.dev_owner_credential
        if key is None or not key.get_secret_value():
            raise DomainError(503, 'Development authentication is not configured')
        return hmac.new(key.get_secret_value().encode(), recipient.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _denomination_valid(product, value):
        if value in [item.package_value for item in product.denominations]:
            return True
        if product.denomination_range:
            try:
                number = Decimal(value)
                low, high, step = (Decimal(product.denomination_range[key]) for key in ('min', 'max', 'step'))
                return (all(item.is_finite() for item in (number, low, high, step)) and step > 0
                        and low <= number <= high and (number - low) % step == 0)
            except (InvalidOperation, KeyError, ValueError):
                pass
        return False

    def _validate_quote(self, svc, purchase, quote: Quote, product: Product, denomination, recipient):
        if quote.product != product or product.id != purchase.product_id:
            raise DomainError(409, 'product_mismatch')
        if product.merchant != purchase.merchant:
            raise DomainError(409, 'merchant_mismatch')
        if product.category not in {'gift_card', 'phone_refill', 'esim'} or product.category != purchase.category:
            raise DomainError(409, 'category_mismatch')
        if product.available is not True:
            raise DomainError(409, 'availability_unverified')
        if product.requires_prepayment:
            raise DomainError(409, 'prepayment_not_supported')
        if quote.denomination != denomination or not self._denomination_valid(product, denomination):
            raise DomainError(409, 'invalid_denomination')
        required = product.recipient_type
        if required and required not in {'phone_number', 'email', 'account_id', 'username'}:
            raise DomainError(409, 'recipient_contract_unverified')
        if required and not recipient:
            raise DomainError(409, 'recipient_required')
        if not required and recipient is not None:
            raise DomainError(409, 'unexpected_recipient')
        if required == 'phone_number' and not re.fullmatch(r'\+[1-9][0-9]{6,14}', recipient):
            raise DomainError(409, 'invalid_recipient')
        if required == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', recipient):
            raise DomainError(409, 'invalid_recipient')
        if recipient is not None and (not recipient.strip() or len(recipient) > 254):
            raise DomainError(409, 'invalid_recipient')
        if purchase.currency != 'USD' or quote.currency != 'USD' or product.currency != 'USD':
            raise DomainError(409, 'unsupported_currency')
        # Preserve immutable agent idempotency payload and the owner's authorized
        # price. A changed price requires a NEW proposal, never a silent mutation.
        if quote.total_cents != purchase.amount_cents:
            raise DomainError(409, 'quoted_price_mismatch')
        if quote.expires_at <= utcnow():
            raise DomainError(409, 'quote_expired')
        permit = svc.permit(purchase.permit_id)
        denial = svc.policy_denial(permit, purchase, exclude_own_reservation=True)
        if denial:
            raise DomainError(409, denial)

    def prepare(self, data: PrepareInput, identity: Identity) -> PreviewOut:
        request_id = str(data.purchase_request_id)
        recipient = data.recipient.get_secret_value() if data.recipient is not None else None
        with spending_service(self.engine) as svc:
            purchase = svc.visible_purchase(request_id, identity.role, identity.subject)
            if purchase.state not in {'pending_approval', 'authorized'}:
                raise DomainError(409, 'Request is not eligible for preparation')
            denial = svc.policy_denial(svc.permit(purchase.permit_id), purchase, exclude_own_reservation=True)
            if denial:
                raise DomainError(409, denial)
            self._no_execution(svc, request_id)
            product_id = purchase.product_id
        product = self.provider.details(product_id)
        quote, blocker = None, None
        try:
            quote = self.provider.quote(product, data.denomination, recipient)
        except ProviderError as exc:
            blocker = exc.code
        with spending_service(self.engine) as svc:
            purchase = svc.visible_purchase(request_id, identity.role, identity.subject)
            self._no_execution(svc, request_id)
            if purchase.state not in {'pending_approval', 'authorized'}:
                raise DomainError(409, 'Request changed during preparation')
            denial = svc.policy_denial(svc.permit(purchase.permit_id), purchase, exclude_own_reservation=True)
            if denial:
                blocker = denial
            if quote is not None:
                try:
                    self._validate_quote(svc, purchase, quote, product, data.denomination, recipient)
                except DomainError as exc:
                    blocker = exc.detail
            preview = PurchasePreview(
                id=str(uuid4()), purchase_request_id=request_id, product_snapshot=product.model_dump(mode='json'),
                denomination=data.denomination, amount_cents=quote.total_cents if quote else None,
                currency=quote.currency if quote else None, payment_method=quote.payment_method if quote else None,
                recipient_digest=self._recipient_digest(recipient), recipient_required=bool(product.recipient_type),
                state='blocked' if blocker else 'ready', blocker=blocker,
                expires_at=min(quote.expires_at, utcnow() + timedelta(seconds=self.settings.bitrefill_preview_ttl_seconds)) if quote else None,
                created_at=utcnow(),
            )
            fingerprint_data = dict(
                id=preview.id, request_id=request_id, product=preview.product_snapshot, denomination=data.denomination,
                amount_cents=preview.amount_cents, currency=preview.currency, payment_method=preview.payment_method,
                recipient_digest=preview.recipient_digest,
                expires_at=preview.expires_at.isoformat() if preview.expires_at else None,
            )
            preview.fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
            svc.session.add(preview)
            svc.session.flush()
            result = PreviewOut.model_validate(preview)
        return result

    def get_preview(self, preview_id, identity):
        with spending_service(self.engine) as svc:
            preview, _ = self._preview(svc, preview_id, identity)
            return PreviewOut.model_validate(preview)

    def _confirmable(self, svc, preview, purchase, data, recipient):
        self._no_execution(svc, purchase.id)
        if preview.state != 'ready' or preview.expires_at is None or preview.expires_at <= utcnow():
            raise DomainError(409, 'Preview is blocked or expired; prepare again')
        if data.preview_fingerprint != preview.fingerprint:
            raise DomainError(409, 'Confirmation does not match the prepared purchase')
        if self._recipient_digest(recipient) != preview.recipient_digest:
            raise DomainError(409, 'Recipient does not match the prepared purchase')
        if purchase.state != 'authorized':
            raise DomainError(409, 'Owner-approved authorization required before execution')
        denial = svc.policy_denial(svc.permit(purchase.permit_id), purchase, exclude_own_reservation=True)
        if denial:
            raise DomainError(409, denial)

    def execute(self, preview_id, data: ConfirmInput, identity: Identity) -> ExecutionOut:
        if identity.role != 'owner':
            raise DomainError(403, 'Owner credential required')
        if data.confirm is not True:
            raise DomainError(409, 'Explicit owner confirmation required')
        if not self.settings.bitrefill_live_purchases_enabled:
            raise DomainError(503, 'Live Bitrefill purchases are disabled')
        recipient = data.recipient.get_secret_value() if data.recipient is not None else None
        with spending_service(self.engine) as svc:
            preview, purchase = self._preview(svc, preview_id, identity)
            self._confirmable(svc, preview, purchase, data, recipient)
            product_id, denomination = purchase.product_id, preview.denomination
        self.provider.ensure_checkout_supported()
        product = self.provider.details(product_id)
        quote = self.provider.quote(product, denomination, recipient)
        with spending_service(self.engine) as svc:
            preview, purchase = self._preview(svc, preview_id, identity)
            self._confirmable(svc, preview, purchase, data, recipient)
            self._validate_quote(svc, purchase, quote, product, denomination, recipient)
            if (quote.total_cents != preview.amount_cents or quote.currency != preview.currency
                    or quote.payment_method != preview.payment_method or product.model_dump(mode='json') != preview.product_snapshot):
                raise DomainError(409, 'Quote changed; a new preparation and owner confirmation are required')
            execution = PurchaseExecution(purchase_request_id=purchase.id, preview_id=preview.id, state='initiating')
            svc.session.add(execution)
            svc.session.flush()
            execution_id = execution.id
        # CRASH BOUNDARY: initiating is durable, unique, and holds the reservation.
        # All errors after this point are uncertain. Never automatically retry.
        try:
            invoice = self.provider.create_invoice(quote, recipient)
            invoice_id = invoice.invoice_id
            if not isinstance(invoice_id, str) or not invoice_id or len(invoice_id) > 128:
                raise ValueError('Invalid invoice identity')
        except Exception:
            with spending_service(self.engine) as svc:
                execution = self._execution(svc, execution_id, identity.subject)
                execution.state, execution.error_code = 'reconciliation_required', 'outcome_uncertain'
                svc.session.flush()
                return ExecutionOut.model_validate(execution)
        # A DB failure here deliberately leaves initiating and the budget held.
        try:
            with spending_service(self.engine) as svc:
                execution = self._execution(svc, execution_id, identity.subject)
                execution.external_invoice_id = invoice_id
                execution.state = 'invoice_created'
                svc.session.flush()
                return ExecutionOut.model_validate(execution)
        except IntegrityError:
            with spending_service(self.engine) as svc:
                execution = self._execution(svc, execution_id, identity.subject)
                execution.state, execution.error_code = 'reconciliation_required', 'invoice_identity_conflict'
                svc.session.flush()
                return ExecutionOut.model_validate(execution)

    def get_execution(self, execution_id, identity):
        if identity.role != 'owner':
            raise DomainError(403, 'Owner credential required')
        with spending_service(self.engine) as svc:
            return ExecutionOut.model_validate(self._execution(svc, execution_id, identity.subject))

    def reconcile(self, execution_id, identity):
        if identity.role != 'owner':
            raise DomainError(403, 'Owner credential required')
        with spending_service(self.engine) as svc:
            execution = self._execution(svc, execution_id, identity.subject)
            if execution.state in {'delivered', 'failed'}:
                return ExecutionOut.model_validate(execution)
            if not execution.external_invoice_id:
                execution.state, execution.error_code = 'reconciliation_required', 'invoice_identity_unknown'
                svc.session.flush()
                return ExecutionOut.model_validate(execution)
            if execution.last_checked_at and utcnow() - execution.last_checked_at < timedelta(seconds=10):
                raise DomainError(429, 'Wait at least 10 seconds between invoice lookups')
            # Persist rate limiting before the read; provider failures must not
            # allow an unlimited polling loop.
            execution.last_checked_at = utcnow()
            invoice_id = execution.external_invoice_id
        try:
            observation = self.provider.invoice(invoice_id)
        except ProviderError:
            with spending_service(self.engine) as svc:
                execution = self._execution(svc, execution_id, identity.subject)
                if execution.state not in {'delivered', 'failed'}:
                    execution.error_code = 'invoice_lookup_failed'
                svc.session.flush()
                return ExecutionOut.model_validate(execution)
        with spending_service(self.engine) as svc:
            execution = self._execution(svc, execution_id, identity.subject)
            if execution.state in {'delivered', 'failed'}:
                return ExecutionOut.model_validate(execution)
            purchase = svc.purchase(execution.purchase_request_id)
            if observation.invoice_id != execution.external_invoice_id:
                execution.state, execution.error_code = 'reconciliation_required', 'invoice_identity_mismatch'
            elif (observation.product_ids != [purchase.product_id] or len(observation.order_statuses) != 1):
                execution.state, execution.error_code = 'reconciliation_required', 'invoice_contents_unverified'
            elif observation.invoice_status == 'complete' and observation.order_statuses == ['delivered']:
                svc.mark_fulfilled(purchase.id, provider_verified=True)
                execution.state, execution.payment_status, execution.delivery_status = 'delivered', 'complete', 'delivered'
                execution.error_code = None
            elif observation.order_statuses == ['refunded']:
                # A failed delivery/payment_error alone does NOT prove funds safe
                # to release. Only a verified returned payment does so here.
                svc.mark_failed(purchase.id, provider_verified=True)
                execution.state, execution.delivery_status = 'failed', 'refunded'
                execution.payment_status, execution.error_code = 'refunded', None
            elif observation.invoice_status in {'blocked', 'denied', 'payment_error', 'unknown', 'complete'} or observation.order_statuses == ['failed']:
                execution.state, execution.error_code = 'reconciliation_required', 'provider_review_required'
            elif execution.payment_status in {'payment_confirmed', 'pending'} and observation.invoice_status in {'unpaid', 'payment_detected'}:
                execution.state, execution.error_code = 'reconciliation_required', 'non_monotonic_invoice_status'
            else:
                execution.payment_status = observation.invoice_status
                execution.delivery_status = observation.order_statuses[0]
                execution.state = 'paid' if observation.invoice_status in {'payment_confirmed', 'pending'} else 'awaiting_payment'
                execution.error_code = None
            execution.updated_at = utcnow()
            svc.session.flush()
            return ExecutionOut.model_validate(execution)
