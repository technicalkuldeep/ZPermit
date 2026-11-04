"""Public demo has zero network capability and per-visitor isolated policy data."""
import httpx
import pytest
from fastapi.testclient import TestClient
from app.public_demo import create_demo_app


@pytest.fixture
def demo(monkeypatch):
    for key in ('BITREFILL_API_KEY','ZPERMIT_BITREFILL_API_KEY','ZPERMIT_DEV_OWNER_CREDENTIAL',
                'ZPERMIT_DEV_AGENT_CREDENTIAL','ZPERMIT_ZCASH_ZALLET_CONFIG','ZPERMIT_ZCASH_ZALLET_DATADIR'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('ZPERMIT_PUBLIC_DEMO','true')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *a,**kw:pytest.fail('Public demo must never call providers'))
    with TestClient(create_demo_app()) as client:
        yield client


def new_session(client):
    r=client.post('/api/demo/sessions', json={})
    assert r.status_code==200,r.text
    d=r.json()
    return {'Authorization':'Bearer '+d['owner']},{'Authorization':'Bearer '+d['agent']}


def test_demo_complete_policy_flow_isolated_and_never_paid(demo):
    owner,agent=new_session(demo)
    data={'name':'Judge demo','agent_id':'demo-agent','currency':'USD',
          'total_limit_cents':1000,'per_purchase_limit_cents':100,
          'allowed_merchants':['swiggy-money-india'],'allowed_categories':['gift_card'],
          'approval_threshold_cents':0,'expires_at':'2030-01-01T00:00:00Z'}
    r=demo.post('/api/permits',headers=owner,json=data)
    assert r.status_code==201,r.text
    pid=r.json()['id']
    proposal={'permit_id':pid,'agent_id':'demo-agent','merchant':'swiggy-money-india','category':'gift_card',
              'product_id':'swiggy-money-india','amount_cents':55,'currency':'USD','external_request_id':'demo-1'}
    r=demo.post('/api/purchase-requests',headers=agent,json=proposal)
    assert r.status_code==200 and r.json()['state']=='pending_approval'
    rid=r.json()['id']
    assert demo.post(f'/api/purchase-requests/{rid}/approve',headers=agent).status_code==403
    assert demo.post(f'/api/purchase-requests/{rid}/approve',headers=owner).json()['state']=='authorized'
    denied=demo.post('/api/purchase-requests',headers=agent,json={**proposal,'external_request_id':'demo-2','amount_cents':1001})
    assert denied.json()['denial_reason']=='per_purchase_limit_exceeded'
    preview=demo.post('/api/bitrefill/purchase-previews',headers=agent,json={'purchase_request_id':rid,'denomination':'50'})
    assert preview.status_code==201 and preview.json()['state']=='blocked'
    snapshot=demo.get('/api/workspace',headers=owner).json()
    assert snapshot['demo'] is True and snapshot['auth_mode']=='isolated_demo_session'
    assert snapshot['permits'][0]['spending']['active_reservations_cents']==55
    assert snapshot['executions']==[] and snapshot['checkout']['execution_available'] is False
    other,_=new_session(demo)
    assert demo.get('/api/workspace',headers=other).json()['permits']==[]
    assert demo.get(f'/api/permits/{pid}',headers=other).status_code==404
    assert demo.post(f'/api/permits/{pid}/revoke',headers=owner).json()['spending']['active_reservations_cents']==0
    product=demo.get('/api/bitrefill/products/swiggy-money-india',headers=agent).json()
    assert 'DEMO ONLY' in product['name']


@pytest.mark.parametrize('path,method',[
    ('/api/bitrefill/balance','get'),('/api/bitrefill/invoices/00000000-0000-0000-0000-000000000000','get'),
    ('/api/bitrefill/purchase-previews/anything/execute','post'),
    ('/api/zcash/mobile/payment-requests','post'),('/api/zcash/public/readiness','get'),
    ('/api/bitrefill/buy-products','post'),('/api/invoices/anything/pay','post')])
def test_public_demo_blocks_real_account_wallet_and_execution_routes(demo,path,method):
    owner,_=new_session(demo)
    assert getattr(demo,method)(path,headers=owner).status_code==403


def test_demo_requires_session_and_enforces_body_and_session_limits(demo):
    assert demo.get('/health').json()['mode']=='public_demo'
    assert demo.get('/api/workspace').status_code==401
    assert demo.get('/api/mode').json()['sample_data'] is True
    assert demo.post('/api/demo/sessions',content=b'x'*16385).status_code==413
    for _ in range(12):new_session(demo)
    assert demo.post('/api/demo/sessions',json={}).status_code==429


def test_private_credentials_cannot_be_attached_to_demo(monkeypatch):
    monkeypatch.setenv('BITREFILL_API_KEY','test-secret-not-real')
    with pytest.raises(RuntimeError,match='must not be configured'):
        create_demo_app()
