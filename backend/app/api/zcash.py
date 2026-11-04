"""Owner-only independent TAZ demo payments, never permit or purchase settlement."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.security import Identity, owner_identity
from app.schemas.zcash import PaymentConfirmation, PaymentInput, PaymentOut
from app.services.zcash import ZcashWorkflow

router = APIRouter(prefix='/api/zcash', tags=['Zcash testnet'])


def workflow(request: Request):
    return ZcashWorkflow(request.app.state.database_engine, request.app.state.settings,
                         request.app.state.zcash_wallet)


@router.get('/readiness')
def readiness(request: Request, owner: Identity = Depends(owner_identity)):
    return request.app.state.zcash_wallet.readiness()


@router.get('/balance')
def balance(request: Request, owner: Identity = Depends(owner_identity)):
    return request.app.state.zcash_wallet.balance()


@router.post('/payment-requests', response_model=PaymentOut, status_code=201)
def prepare(data: PaymentInput, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.prepare(data, owner)


@router.get('/payment-requests/{payment_id}', response_model=PaymentOut)
def get_payment(payment_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.get(str(payment_id), owner)


@router.post('/payment-requests/{payment_id}/confirm', response_model=PaymentOut)
def confirm(payment_id: UUID, data: PaymentConfirmation,
            owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.confirm(str(payment_id), data, owner)


@router.post('/payment-requests/{payment_id}/refresh', response_model=PaymentOut)
def refresh(payment_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.refresh(str(payment_id), owner)


@router.get('/payment-requests/{payment_id}/evidence')
def evidence(payment_id: UUID, request: Request,
             owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    payment = svc.get(str(payment_id), owner)
    return request.app.state.zcash_wallet.evidence(payment.txid)
