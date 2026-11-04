"""Owner-only ZIP-321 handoff. The phone owns approval, signing and sending."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.core.security import Identity, owner_identity
from app.schemas.mobile_payment import MobileEvidenceOut, MobilePaymentInput, MobilePaymentOut
from app.schemas.public_testnet import ObserveTransactionInput
from app.services.mobile_payment import MobilePaymentWorkflow, qr_png


def no_cache(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/zcash/mobile/payment-requests', tags=['Mobile wallet payment requests'],
                   dependencies=[Depends(no_cache)])


def workflow(request: Request):
    return MobilePaymentWorkflow(request.app.state.database_engine, request.app.state.settings,
                                 request.app.state.public_testnet)


@router.post('', response_model=MobilePaymentOut, status_code=201)
def prepare(data: MobilePaymentInput, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.prepare(data, owner)


@router.get('/{request_id}', response_model=MobilePaymentOut)
def get(request_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.get(str(request_id), owner)


@router.get('/{request_id}/qr.png', response_class=Response)
def qr(request_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    payment = svc.get(str(request_id), owner)
    return Response(qr_png(payment.payment_uri), media_type='image/png', headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/{request_id}/evidence', response_model=MobileEvidenceOut)
def evidence(request_id: UUID, data: ObserveTransactionInput,
             owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.evidence(str(request_id), data, owner)
