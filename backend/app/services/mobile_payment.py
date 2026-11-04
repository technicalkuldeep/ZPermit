"""Single-recipient ZIP-321 requests for external phone-wallet review only."""
import base64
from io import BytesIO

import qrcode
from sqlalchemy import select

from app.models.mobile_payment import MobilePaymentEvidence, MobilePaymentRequest
from app.schemas.mobile_payment import MobileEvidenceOut, MobilePaymentOut
from app.services.public_testnet import PublicTestnetWorkflow
from app.services.spending import DomainError
from app.services.zcash import ZcashWorkflow


def amount_taz(zatoshis):
    # Integer-only formatting: no scientific notation or binary floating point.
    return f'{zatoshis // 100_000_000}.{zatoshis % 100_000_000:08d}'.rstrip('0').rstrip('.')


def payment_uri(destination, zatoshis, memo):
    uri = f'zcash:{destination}?amount={amount_taz(zatoshis)}'
    if memo is not None:
        encoded = base64.urlsafe_b64encode(memo.encode('utf-8')).decode('ascii').rstrip('=')
        uri += '&memo=' + encoded
    return uri


def qr_png(uri):
    # QR encodes the request directly; no third-party QR service or wallet API.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


class MobilePaymentWorkflow:
    def __init__(self, engine, settings, client):
        self.client = client
        self.transaction = ZcashWorkflow(engine, settings, None).transaction
        self.observations = PublicTestnetWorkflow(engine, settings, client)

    def row(self, session, request_id, owner):
        row = session.get(MobilePaymentRequest, request_id)
        if row is None or row.owner_id != owner.subject:
            raise DomainError(404, 'Mobile payment request not found')
        return row

    def output(self, session, row):
        link = session.get(MobilePaymentEvidence, row.id)
        return MobilePaymentOut(
            id=row.id, destination=row.destination, amount_zatoshis=row.amount_zatoshis,
            amount_taz=amount_taz(row.amount_zatoshis), memo=row.memo,
            payment_uri=payment_uri(row.destination, row.amount_zatoshis, row.memo),
            qr_path=f'/api/zcash/mobile/payment-requests/{row.id}/qr.png',
            observation_id=link.observation_id if link else None, created_at=row.created_at)

    def prepare(self, data, owner):
        # Uses the existing official-library checksum/network/receiver decoder.
        # No local wallet or public network needed for request generation.
        self.client.inspector.address(data.destination)
        with self.transaction() as session:
            existing = session.scalar(select(MobilePaymentRequest).where(
                MobilePaymentRequest.owner_id == owner.subject,
                MobilePaymentRequest.request_key == data.request_key))
            if existing:
                if (existing.destination, existing.amount_zatoshis, existing.memo) != (
                        data.destination, data.amount_zatoshis, data.memo):
                    raise DomainError(409, 'Mobile request key conflicts with existing payment terms')
                return self.output(session, existing)
            row = MobilePaymentRequest(owner_id=owner.subject, **data.model_dump())
            session.add(row)
            session.flush()
            result = self.output(session, row)
        return result

    def get(self, request_id, owner):
        with self.transaction() as session:
            return self.output(session, self.row(session, request_id, owner))

    def check_link(self, session, request_id, txid):
        link = session.get(MobilePaymentEvidence, request_id)
        if link:
            # Existing protected workflow resolves the owner separately; no caller
            # can change a saved phone request's txid by submitting a new key.
            from app.models.public_testnet import PublicTransactionObservation
            observation = session.get(PublicTransactionObservation, link.observation_id)
            if observation.txid != txid:
                raise DomainError(409, 'Request already has a transaction observation; do not resend blindly')
        return link

    def evidence(self, request_id, data, owner):
        with self.transaction() as session:
            self.row(session, request_id, owner)
            self.check_link(session, request_id, data.txid)
        # Preserve the existing verified, owner-protected, idempotent evidence path.
        # Its chain observation never proves recipient, amount, memo or ownership.
        observation = self.observations.record(data, owner)
        with self.transaction() as session:
            self.row(session, request_id, owner)
            link = self.check_link(session, request_id, data.txid)
            if link is None:
                other = session.scalar(select(MobilePaymentEvidence).where(
                    MobilePaymentEvidence.observation_id == observation.id))
                if other:
                    raise DomainError(409, 'Transaction observation already linked to another request')
                session.add(MobilePaymentEvidence(request_id=request_id, observation_id=observation.id))
        return MobileEvidenceOut(request_id=request_id, observation=observation)
