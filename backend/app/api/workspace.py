"""Owner-scoped application reads; reuse existing policies and output schemas."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.core.security import Identity, owner_identity, development_identity
from app.models.spending import Permit, PurchaseRequest
from app.models.bitrefill import PurchasePreview, PurchaseExecution
from app.models.mobile_payment import MobilePaymentRequest
from app.models.public_testnet import PublicTransactionObservation
from app.schemas.spending import PurchaseOut
from app.schemas.bitrefill import PreviewOut, ExecutionOut
from app.schemas.public_testnet import PublicObservationOut
from app.services.mobile_payment import MobilePaymentWorkflow
from app.services.spending import spending_service

router = APIRouter(prefix='/api/workspace', tags=['Owner workspace'])


@router.get('')
def workspace(request: Request, response: Response, owner: Identity = Depends(owner_identity)):
    response.headers['Cache-Control'] = 'no-store'
    config = request.app.state.settings
    # No provider requests here. Network integrations fail independently of local data.
    with spending_service(request.app.state.database_engine) as svc:
        permit_ids = select(Permit.id).where(Permit.owner_id == owner.subject)
        request_ids = select(PurchaseRequest.id).where(PurchaseRequest.permit_id.in_(permit_ids))
        purchases = svc.session.scalars(select(PurchaseRequest).where(
            PurchaseRequest.permit_id.in_(permit_ids)).order_by(PurchaseRequest.created_at.desc())).all()
        previews = svc.session.scalars(select(PurchasePreview).where(
            PurchasePreview.purchase_request_id.in_(request_ids)).order_by(PurchasePreview.created_at.desc())).all()
        executions = svc.session.scalars(select(PurchaseExecution).where(
            PurchaseExecution.purchase_request_id.in_(request_ids)).order_by(PurchaseExecution.created_at.desc())).all()
        mobile = MobilePaymentWorkflow(request.app.state.database_engine, config, request.app.state.public_testnet)
        mobile_rows = svc.session.scalars(select(MobilePaymentRequest).where(
            MobilePaymentRequest.owner_id == owner.subject).order_by(MobilePaymentRequest.created_at.desc())).all()
        observations = svc.session.scalars(select(PublicTransactionObservation).where(
            PublicTransactionObservation.owner_id == owner.subject).order_by(PublicTransactionObservation.created_at.desc())).all()
        return dict(agent_id=config.dev_agent_id, owner_id=owner.subject,
                    auth_mode='isolated_demo_session' if config.public_demo else 'local_development',
                    demo=config.public_demo,
                    checkout=dict(execution_available=False, blocker='maximum_debit_unbounded',
                                  live_gate_enabled=config.bitrefill_live_purchases_enabled),
                    public_reads_enabled=config.zcash_public_reads_enabled,
                    permits=svc.list_permits(owner.subject),
                    purchases=[PurchaseOut.model_validate(x) for x in purchases],
                    previews=[PreviewOut.model_validate(x) for x in previews],
                    executions=[ExecutionOut.model_validate(x) for x in executions],
                    mobile_requests=[mobile.output(svc.session, x) for x in mobile_rows],
                    observations=[PublicObservationOut.model_validate(x) for x in observations])


@router.get('/identity')
def identity(response: Response, identity: Identity = Depends(development_identity)):
    response.headers['Cache-Control'] = 'no-store'
    return {'role': identity.role, 'subject': identity.subject}
