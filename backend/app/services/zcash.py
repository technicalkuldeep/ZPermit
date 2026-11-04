"""Durable claim BEFORE send; lost/ambiguous results can never trigger a resend."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.zcash import OPID, TXID, ZcashError
from app.models.spending import utcnow
from app.models.zcash import TestnetPayment
from app.schemas.zcash import PaymentOut
from app.services.spending import DomainError


class ZcashWorkflow:
    def __init__(self, engine, settings, wallet):
        self.engine, self.config, self.wallet = engine, settings, wallet

    @contextmanager
    def transaction(self):
        if self.engine.dialect.name != 'sqlite':
            raise DomainError(503, 'Testnet payment serialization requires SQLite')
        with Session(self.engine, expire_on_commit=False) as s:
            s.connection().exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield s
                s.commit()
            except BaseException:
                s.rollback()
                raise

    def row(self, s, payment_id, owner):
        p = s.get(TestnetPayment, payment_id)
        if p is None or p.owner_id != owner.subject:
            raise DomainError(404, 'Testnet payment not found')
        return p

    def fingerprint(self, source, destination, amount):
        payload = {'network': 'test', 'source': source, 'destination': destination,
                   'amount_zatoshis': amount, 'account_id': self.config.zcash_account_id,
                   'privacy': 'FullPrivacy', 'fee': 'automatic_zip317',
                   'wallet_config': self.config.zcash_zallet_config,
                   'wallet_datadir': self.config.zcash_zallet_datadir}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def prepare(self, data, owner):
        self.wallet.readiness()
        source = self.wallet.address(self.config.zcash_source_address)
        destination = self.wallet.address(data.destination)
        fingerprint = self.fingerprint(source, destination, data.amount_zatoshis)
        with self.transaction() as s:
            existing = s.scalar(select(TestnetPayment).where(
                TestnetPayment.owner_id == owner.subject, TestnetPayment.request_key == data.request_key))
            if existing:
                if existing.fingerprint != fingerprint:
                    raise DomainError(409, 'Testnet request key conflicts with existing payment')
                return PaymentOut.model_validate(existing)
            p = TestnetPayment(owner_id=owner.subject, request_key=data.request_key,
                               source=source, destination=destination, account_id=self.config.zcash_account_id,
                               amount_zatoshis=data.amount_zatoshis, fingerprint=fingerprint,
                               expires_at=utcnow() + timedelta(seconds=self.config.zcash_request_ttl_seconds))
            s.add(p)
            s.flush()
            result = PaymentOut.model_validate(p)
        return result

    def get(self, payment_id, owner):
        with self.transaction() as s:
            return PaymentOut.model_validate(self.row(s, payment_id, owner))

    def confirm(self, payment_id, data, owner):
        if not self.config.zcash_live_broadcast_enabled:
            raise DomainError(409, 'Live testnet broadcast is disabled')
        # Retry after a completed/uncertain send is read-only and never dispatches.
        current = self.get(payment_id, owner)
        if current.fingerprint != data.fingerprint:
            raise DomainError(409, 'Confirmation does not match payment')
        if current.state != 'pending_approval':
            return current
        self.wallet.readiness()
        source = self.wallet.address(self.config.zcash_source_address)
        with self.transaction() as s:
            p = self.row(s, payment_id, owner)
            if p.state != 'pending_approval':
                return PaymentOut.model_validate(p)
            if p.expires_at <= utcnow():
                raise DomainError(409, 'Testnet payment approval expired')
            if (p.source != source or p.fingerprint != self.fingerprint(source, p.destination, p.amount_zatoshis)
                    or p.fingerprint != data.fingerprint):
                raise DomainError(409, 'Wallet configuration changed; create a new request')
            # Commit the claim separately from any wallet side effect. A process crash
            # leaves initiating, which is never automatically sent again.
            p.state = 'initiating'
        try:
            opid = self.wallet.send(current.source, current.destination, current.amount_zatoshis)
            if not isinstance(opid, str) or not OPID.fullmatch(opid):
                raise ZcashError('wallet_response_invalid')
        except Exception:
            # Includes timeout, rejection, parsing errors and unexpected adapter errors.
            # No raw exception text; no guessing whether the daemon accepted the send.
            with self.transaction() as s:
                p = self.row(s, payment_id, owner)
                p.state, p.error_code = 'uncertain', 'send_result_unknown'
            return self.get(payment_id, owner)
        with self.transaction() as s:
            p = self.row(s, payment_id, owner)
            p.state, p.operation_id = 'submitted', opid
        return self.get(payment_id, owner)

    def refresh(self, payment_id, owner):
        current = self.get(payment_id, owner)
        if current.state == 'pending_approval':
            return current
        # Read-only reconciliation. An operation lost on wallet restart cannot be
        # recovered by creating a new payment. Mentor must inspect wallet history.
        self.wallet.readiness()
        with self.transaction() as s:
            p = self.row(s, payment_id, owner)
            if p.operation_id and not p.txid:
                try:
                    op = self.wallet.operation(p.operation_id)
                    if op['status'] == 'success':
                        result = op['result']
                        txids = result['txids']
                        if (not isinstance(txids, list) or len(txids) != 1
                                or not isinstance(txids[0], str) or not TXID.fullmatch(txids[0])
                                or type(result['broadcast']) is not bool):
                            raise ZcashError('wallet_response_invalid')
                        p.txid = txids[0]
                        p.state = 'broadcast' if result['broadcast'] else 'not_broadcast'
                        p.error_code = None
                    elif op['status'] in {'failed', 'cancelled'}:
                        p.state, p.error_code = 'failed', 'wallet_operation_failed'
                    else:
                        p.state, p.error_code = 'submitted', None
                except (ZcashError, KeyError, TypeError):
                    p.state, p.error_code = 'uncertain', 'operation_result_unknown'
            elif p.state == 'initiating':
                p.state, p.error_code = 'uncertain', 'send_result_unknown'
            if p.txid:
                try:
                    observation = self.wallet.transaction(p.txid)
                    p.confirmations = observation['confirmations']
                    p.transaction_status = observation['status']
                    p.error_code = None
                except ZcashError:
                    # Preserve the known txid even if the subsequent read fails.
                    p.error_code = 'transaction_lookup_unavailable'
            s.flush()
            result = PaymentOut.model_validate(p)
        return result
