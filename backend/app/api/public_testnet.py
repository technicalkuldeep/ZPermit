"""Owner-only network observations; no wallet control, balance claims, or send route."""
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.security import Identity, owner_identity
from app.schemas.public_testnet import ObserveTransactionInput, PublicAddressInput, PublicObservationOut
from app.services.public_testnet import PublicTestnetWorkflow

router = APIRouter(prefix='/api/zcash/public', tags=['Public testnet observations'])


def workflow(request: Request):
    return PublicTestnetWorkflow(request.app.state.database_engine, request.app.state.settings,
                                 request.app.state.public_testnet)


@router.get('/readiness')
def readiness(request: Request, owner: Identity = Depends(owner_identity)):
    return request.app.state.public_testnet.readiness()


@router.get('/receiving-address')
def address(request: Request, owner: Identity = Depends(owner_identity)):
    return request.app.state.public_testnet.receiving_address()


@router.post('/validate-address')
def validate(data: PublicAddressInput, request: Request, owner: Identity = Depends(owner_identity)):
    return request.app.state.public_testnet.inspector.address(data.address)


@router.post('/transactions', response_model=PublicObservationOut, status_code=201)
def record(data: ObserveTransactionInput, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.record(data, owner)


@router.get('/transactions/{observation_id}', response_model=PublicObservationOut)
def get(observation_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.get(str(observation_id), owner)


@router.post('/transactions/{observation_id}/refresh', response_model=PublicObservationOut)
def refresh(observation_id: UUID, owner: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.refresh(str(observation_id), owner)
