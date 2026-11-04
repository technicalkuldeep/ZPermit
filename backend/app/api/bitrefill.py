"""No direct provider buy route: execution requires an exact owner confirmation."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.security import Identity, development_identity, owner_identity
from app.schemas.bitrefill import ConfirmInput, ExecutionOut, PrepareInput, PreviewOut, Product
from app.services.bitrefill import BitrefillWorkflow

router = APIRouter(prefix='/api/bitrefill', tags=['Bitrefill'])


def workflow(request: Request):
    return BitrefillWorkflow(request.app.state.database_engine, request.app.state.settings,
                            request.app.state.bitrefill_provider)


@router.get('/products', response_model=list[Product])
def search_products(request: Request,
                    query: Annotated[str, Query(min_length=1, max_length=100)],
                    intent: Annotated[str, Query(min_length=1, max_length=500)],
                    country: Annotated[str, Query(pattern=r'^[A-Z]{2}$')] = 'US',
                    product_type: Annotated[str | None, Query(max_length=50)] = None,
                    identity: Identity = Depends(development_identity)):
    return request.app.state.bitrefill_provider.search(query, intent, country, product_type)


@router.get('/products/{product_id}', response_model=Product)
def product_details(request: Request,
                    product_id: Annotated[str, Path(min_length=1, max_length=128)],
                    identity: Identity = Depends(development_identity)):
    return request.app.state.bitrefill_provider.details(product_id)


@router.post('/purchase-previews', response_model=PreviewOut, status_code=201)
def prepare(data: PrepareInput, identity: Identity = Depends(development_identity), svc=Depends(workflow)):
    return svc.prepare(data, identity)


@router.get('/purchase-previews/{preview_id}', response_model=PreviewOut)
def get_preview(preview_id: UUID, identity: Identity = Depends(development_identity), svc=Depends(workflow)):
    return svc.get_preview(str(preview_id), identity)


@router.post('/purchase-previews/{preview_id}/execute', response_model=ExecutionOut)
def execute(preview_id: UUID, data: ConfirmInput,
            identity: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.execute(str(preview_id), data, identity)


@router.get('/executions/{execution_id}', response_model=ExecutionOut)
def get_execution(execution_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.get_execution(str(execution_id), identity)


@router.post('/executions/{execution_id}/reconcile', response_model=ExecutionOut)
def reconcile(execution_id: UUID, identity: Identity = Depends(owner_identity), svc=Depends(workflow)):
    return svc.reconcile(str(execution_id), identity)
