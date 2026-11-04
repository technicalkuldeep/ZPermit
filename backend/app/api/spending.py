from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.security import Identity, agent_identity, development_identity, owner_identity
from app.schemas.spending import PermitCreate, PermitOut, PurchaseCreate, PurchaseOut
from app.services.spending import spending_service

router = APIRouter(prefix='/api')


def service(request: Request):
    with spending_service(request.app.state.database_engine) as instance:
        yield instance


@router.post('/permits', response_model=PermitOut, status_code=201, tags=['owner permits'])
def create_permit(data: PermitCreate, identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.create_permit(data, identity.subject)


@router.get('/permits', response_model=list[PermitOut], tags=['owner permits'])
def list_permits(identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.list_permits(identity.subject)


@router.get('/permits/{permit_id}', response_model=PermitOut, tags=['owner permits'])
def get_permit(permit_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.permit_output(svc.permit(str(permit_id), identity.subject))


@router.post('/permits/{permit_id}/revoke', response_model=PermitOut, tags=['owner permits'])
def revoke(permit_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.revoke(str(permit_id), identity.subject)


@router.post('/purchase-requests', response_model=PurchaseOut, tags=['agent proposals'])
def submit(data: PurchaseCreate, identity: Identity = Depends(agent_identity), svc=Depends(service, scope="function")):
    return svc.submit(data, identity.subject)


@router.get('/purchase-requests/{request_id}', response_model=PurchaseOut, tags=['purchase requests'])
def get_purchase(request_id: UUID, identity: Identity = Depends(development_identity), svc=Depends(service, scope="function")):
    return svc.visible_purchase(str(request_id), identity.role, identity.subject)


@router.post('/purchase-requests/{request_id}/approve', response_model=PurchaseOut, tags=['owner decisions'])
def approve(request_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.approve(str(request_id), identity.subject)


@router.post('/purchase-requests/{request_id}/reject', response_model=PurchaseOut, tags=['owner decisions'])
def reject(request_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(service, scope="function")):
    return svc.reject(str(request_id), identity.subject)


@router.post('/purchase-requests/{request_id}/cancel', response_model=PurchaseOut, tags=['purchase requests'])
def cancel(request_id: UUID, identity: Identity = Depends(development_identity), svc=Depends(service, scope="function")):
    return svc.cancel(str(request_id), identity.role, identity.subject)
