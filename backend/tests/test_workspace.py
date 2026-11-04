from test_spending import world
from app.integrations.bitrefill import ProviderError


def test_workspace_reads_real_policy_state_and_scopes_owner(world):
    permit = world.permit()
    purchase = world.submit(permit)
    r = world.client.get('/api/workspace', headers=world.owner)
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-store'
    body = r.json()
    assert body['purchases'][0]['id'] == purchase['id']
    assert body['permits'][0]['spending']['active_reservations_cents'] == 800
    assert body['checkout']['execution_available'] is False
    assert body['checkout']['blocker'] == 'maximum_debit_unbounded'
    assert body['mobile_requests'] == [] and body['observations'] == []
    assert world.settings.dev_owner_credential.get_secret_value() not in r.text
    assert world.client.get('/api/workspace',headers=world.agent).status_code == 403
    world.settings.dev_owner_id = 'another-owner'
    other = world.client.get('/api/workspace',headers=world.owner).json()
    assert other['permits'] == [] and other['purchases'] == []


def test_invoice_read_owner_only_no_settlement(world):
    class Reader:
        def inspect_invoice(self, invoice_id):
            return {'invoice_id':invoice_id,'payment_status':'unpaid','payment_price_raw':'682',
                    'payment_currency':'BTC','maximum_usd_debit_verified':False}
    world.client.app.state.bitrefill_rest_reader = Reader()
    path='/api/bitrefill/invoices/1f81dedb-ea5d-4065-9332-81d573e98f3a'
    assert world.client.get(path,headers=world.agent).status_code == 403
    r=world.client.get(path,headers=world.owner)
    assert r.status_code == 200 and r.json()['payment_status']=='unpaid'
    assert r.headers['cache-control']=='no-store'
    assert world.client.post(path+'/pay',headers=world.owner).status_code == 404
    assert world.client.get('/api/workspace',headers=world.owner).json()['executions']==[]


def test_provider_invoice_read_failure_stays_sanitized(world):
    class Reader:
        def inspect_invoice(self, invoice_id):
            raise ProviderError('timeout',504)
    world.client.app.state.bitrefill_rest_reader=Reader()
    r=world.client.get('/api/bitrefill/invoices/1f81dedb-ea5d-4065-9332-81d573e98f3a',headers=world.owner)
    assert r.status_code==504 and r.json()['detail']['code']=='timeout'


def test_built_frontend_serves_without_masking_missing_api_routes(world):
    from pathlib import Path
    dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist' / 'index.html'
    if dist.is_file():
        response = world.client.get('/')
        assert response.status_code == 200
        assert '<div id="root">' in response.text
        assert response.headers['cache-control'] == 'no-cache'
    assert world.client.get('/api/does-not-exist', headers=world.owner).status_code == 404
    assert world.client.post('/api/does-not-exist', headers=world.owner).status_code == 404
