"""Read-only wallet-initiated evidence; never executes or settles payments."""
from sqlalchemy import select

from app.integrations.zcash import ZcashError
from app.models.public_testnet import PublicTransactionObservation
from app.models.spending import utcnow
from app.schemas.public_testnet import PublicObservationOut
from app.services.spending import DomainError
from app.services.zcash import ZcashWorkflow


class PublicTestnetWorkflow:
    def __init__(self, engine, settings, client):
        self.client = client
        self.transaction = ZcashWorkflow(engine, settings, None).transaction

    def row(self, s, observation_id, owner):
        row = s.get(PublicTransactionObservation, observation_id)
        if row is None or row.owner_id != owner.subject:
            raise DomainError(404, 'Public transaction observation not found')
        return row

    def existing(self, s, data, owner):
        r = s.scalar(select(PublicTransactionObservation).where(
            PublicTransactionObservation.owner_id == owner.subject,
            PublicTransactionObservation.request_key == data.request_key))
        if r and r.txid != data.txid:
            raise DomainError(409, 'Observation request key conflicts with existing transaction')
        if not r and s.scalar(select(PublicTransactionObservation.id).where(
                PublicTransactionObservation.owner_id == owner.subject,
                PublicTransactionObservation.txid == data.txid)):
            raise DomainError(409, 'Transaction already recorded; use its existing observation')
        return r

    def record(self, data, owner):
        with self.transaction() as s:
            existing = self.existing(s, data, owner)
            if existing:
                return PublicObservationOut.model_validate(existing)
        # Verify before recording; a syntactically plausible txid proves nothing.
        evidence = self.client.transaction(data.txid)
        with self.transaction() as s:
            existing = self.existing(s, data, owner)
            if existing:
                return PublicObservationOut.model_validate(existing)
            row = PublicTransactionObservation(owner_id=owner.subject, request_key=data.request_key,
                                               txid=data.txid, evidence=evidence)
            s.add(row)
            s.flush()
            result = PublicObservationOut.model_validate(row)
        return result

    def get(self, observation_id, owner):
        with self.transaction() as s:
            return PublicObservationOut.model_validate(self.row(s, observation_id, owner))

    def refresh(self, observation_id, owner):
        # Serialize observations so a slower stale check cannot overwrite a newer one.
        # Retain last good evidence on failure, visibly marked as a failed latest check.
        with self.transaction() as s:
            r = self.row(s, observation_id, owner)
            try:
                r.evidence = self.client.transaction(r.txid)
                r.last_check_succeeded, r.error_code = True, None
                r.last_verified_at = utcnow()
            except ZcashError as exc:
                r.last_check_succeeded, r.error_code = False, exc.code
            r.last_checked_at = utcnow()
            s.flush()
            result = PublicObservationOut.model_validate(r)
        return result
