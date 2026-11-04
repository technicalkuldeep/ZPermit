"""All provider traffic is mocked. Quotes are INTERNAL domain fixtures, not
captured Bitrefill responses and not evidence that live checkout is supported.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from secrets import token_urlsafe
from threading import Barrier

import httpx
import pytest
import toon_format
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_spending import world  # reuse existing isolated database/API fixture
from app.core.config import Settings
from app.core.security import Identity
from app.integrations.bitrefill import BitrefillClient, ProviderError
from app.models.bitrefill import PurchaseExecution, PurchasePreview
from app.models.spending import Permit, utcnow
from app.schemas.bitrefill import CreatedInvoice, Denomination, InvoiceObservation, Product, Quote
from app.services.spending import DomainError, spending_service


@pytest.fixture(autouse=True)
def block_live_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Live network traffic is forbidden in Bitrefill tests')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)


class MockProvider:
    """Normalized in-process contract double; never interprets a provider schema."""
    def __init__(self):
        self.product = Product(id='catalog-shop', name='Mock catalog product', product_type='gift_card',
                               country='US', currency='USD', available=True,
                               denominations=[Denomination(package_value='8')], purchase_blocker=None)
        self.cost = 800
        self.buy_calls = 0
        self.detail_calls = 0
        self.error = None
        self.details_error = None
        self.observation = InvoiceObservation(invoice_id='provider-invoice-1', invoice_status='unpaid',
                                              order_statuses=['created'], product_ids=['catalog-shop'])

    def search(self, query, intent, country, product_type):
        return [self.product]

    def details(self, product_id):
        self.detail_calls += 1
        if self.details_error:
            raise self.details_error
        return self.product.model_copy(deep=True)

    def quote(self, product, denomination, recipient):
        return Quote(product=product, denomination=denomination, total_cents=self.cost,
                     currency='USD', payment_method='fiat_card', expires_at=utcnow() + timedelta(minutes=3))

    def ensure_checkout_supported(self):
        pass

    def create_invoice(self, quote, recipient):
        self.buy_calls += 1
        if self.error:
            raise self.error
        return CreatedInvoice(invoice_id='provider-invoice-1')

    def invoice(self, invoice_id):
        return self.observation


@pytest.fixture
def provider(world):
    provider = MockProvider()
    world.client.app.state.bitrefill_provider = provider
    return provider


def purchase(world, **policy):
    permit = world.permit(allowed_merchants=['catalog-shop'], allowed_categories=['gift_card'], **policy)
    request = world.submit(permit, merchant='catalog-shop', category='gift_card', product_id='catalog-shop')
    return permit, request


def prepare(world, request, **overrides):
    data = {'purchase_request_id': request['id'], 'denomination': '8'}
    data.update(overrides)
    return world.client.post('/api/bitrefill/purchase-previews', json=data, headers=world.agent)


def execute(world, preview, headers=None, **overrides):
    data = {'preview_fingerprint': preview['fingerprint'], 'confirm': True}
    data.update(overrides)
    return world.client.post(f"/api/bitrefill/purchase-previews/{preview['id']}/execute", json=data,
                             headers=world.owner if headers is None else headers)


def execution(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True  # normalized mock only
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    assert preview['state'] == 'ready'
    response = execute(world, preview)
    assert response.status_code == 200, response.text
    return permit, request, preview, response.json()


def reconcile(world, record):
    return world.client.post(f"/api/bitrefill/executions/{record['id']}/reconcile", headers=world.owner)


def allow_next_poll(world, record):
    with Session(world.engine) as session:
        session.get(PurchaseExecution, record['id']).last_checked_at = utcnow() - timedelta(seconds=11)
        session.commit()


def test_mock_discovery_does_not_reserve_budget(world, provider):
    permit, _ = purchase(world)
    before = world.summary(permit)
    result = world.client.get('/api/bitrefill/products', params={'query': 'catalog', 'intent': 'Find supplies'}, headers=world.agent)
    assert result.status_code == 200
    assert result.json()[0]['id'] == 'catalog-shop'
    result = world.client.get('/api/bitrefill/products/catalog-shop', headers=world.agent)
    assert result.status_code == 200
    assert world.summary(permit) == before
    assert provider.buy_calls == 0


def test_prepare_price_matches_reservation_and_preserves_request(world, provider):
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    assert preview['state'] == 'ready'
    assert preview['amount_cents'] == request['amount_cents'] == 800
    assert preview['currency'] == 'USD'
    assert world.summary(permit)['active_reservations_cents'] == 800
    assert world.client.get(f"/api/purchase-requests/{request['id']}", headers=world.agent).json() == request
    assert provider.buy_calls == 0


def test_pending_approval_can_prepare_but_not_execute(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world, approval_threshold_cents=0)
    preview = prepare(world, request).json()
    assert preview['state'] == 'ready'
    assert world.summary(permit)['active_reservations_cents'] == 0
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0
    assert world.action(request, 'approve').json()['state'] == 'authorized'
    assert execute(world, preview).json()['state'] == 'invoice_created'
    assert world.summary(permit)['active_reservations_cents'] == 800


@pytest.mark.parametrize('cost', [799, 801, 1200])
def test_price_mismatch_blocks_preparation_without_budget_mutation(world, provider, cost):
    permit, request = purchase(world)
    provider.cost = cost
    preview = prepare(world, request).json()
    assert preview['state'] == 'blocked'
    assert preview['blocker'] == 'quoted_price_mismatch'
    assert world.summary(permit)['active_reservations_cents'] == 800
    world.settings.bitrefill_live_purchases_enabled = True
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0


@pytest.mark.parametrize('mutation,reason', [
    ({'id': 'other-product'}, 'product_mismatch'),
    ({'product_type': 'phone_refill'}, 'category_mismatch'),
    ({'available': False}, 'availability_unverified'),
    ({'available': None}, 'availability_unverified'),
    ({'currency': 'USDC'}, 'unsupported_currency'),
    ({'requires_prepayment': True}, 'prepayment_not_supported'),
    ({'denominations': [Denomination(package_value='10')]}, 'invalid_denomination'),
])
def test_provider_metadata_mismatches(world, provider, mutation, reason):
    _, request = purchase(world)
    provider.product = provider.product.model_copy(update=mutation)
    preview = prepare(world, request).json()
    assert preview['state'] == 'blocked'
    assert preview['blocker'] == reason


def test_agent_claimed_merchant_is_not_trusted(world, provider):
    permit = world.permit(allowed_merchants=['claimed-shop'], allowed_categories=['gift_card'])
    request = world.submit(permit, merchant='claimed-shop', category='gift_card', product_id='catalog-shop')
    preview = prepare(world, request).json()
    assert preview['blocker'] == 'merchant_mismatch'


@pytest.mark.parametrize('change', ['revoke', 'expire'])
def test_rechecks_permit_on_preparation_and_execution(world, provider, change):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    if change == 'revoke':
        world.client.post(f"/api/permits/{permit['id']}/revoke", headers=world.owner)
    else:
        world.expire(permit)
    assert prepare(world, request).status_code == 409
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0


def test_fresh_price_increase_requires_new_request(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    provider.cost = 801
    assert execute(world, preview).status_code == 409
    assert world.summary(permit)['active_reservations_cents'] == 800
    assert provider.buy_calls == 0


def test_stale_preview_and_changed_fingerprint_are_rejected(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    _, request = purchase(world)
    preview = prepare(world, request).json()
    assert execute(world, preview, preview_fingerprint='0' * 64).status_code == 409
    with Session(world.engine) as session:
        session.get(PurchasePreview, preview['id']).expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0


@pytest.mark.parametrize('confirmation', [False, 1, 'true', None])
def test_explicit_strict_owner_confirmation_required(world, provider, confirmation):
    world.settings.bitrefill_live_purchases_enabled = True
    _, request = purchase(world)
    preview = prepare(world, request).json()
    assert execute(world, preview, confirm=confirmation).status_code == 422
    assert provider.buy_calls == 0


def test_live_switch_disabled_by_default_even_for_valid_owner_confirmation(world, provider):
    assert Settings(_env_file=None).bitrefill_live_purchases_enabled is False
    _, request = purchase(world)
    preview = prepare(world, request).json()
    assert execute(world, preview).status_code == 503
    assert provider.buy_calls == 0


def test_agent_cannot_execute_or_reconcile(world, provider):
    _, _, preview, record = execution(world, provider)
    assert execute(world, preview, headers=world.agent).status_code == 403
    for path in [f"/api/bitrefill/executions/{record['id']}", f"/api/bitrefill/executions/{record['id']}/reconcile"]:
        response = world.client.post(path, headers=world.agent) if path.endswith('reconcile') else world.client.get(path, headers=world.agent)
        assert response.status_code == 403
    assert provider.buy_calls == 1


def test_duplicate_execution_is_not_a_second_invoice(world, provider):
    permit, _, preview, record = execution(world, provider)
    assert record['state'] == 'invoice_created'
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 1
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_created_invoice_is_not_paid_or_fulfilled(world, provider):
    permit, request, _, record = execution(world, provider)
    assert record['payment_status'] == 'unknown'
    assert world.client.get(f"/api/purchase-requests/{request['id']}", headers=world.owner).json()['state'] == 'authorized'
    observed = reconcile(world, record).json()
    assert observed['state'] == 'awaiting_payment'
    assert observed['payment_status'] == 'unpaid'
    assert world.summary(permit)['fulfilled_spend_cents'] == 0
    assert world.summary(permit)['active_reservations_cents'] == 800
    assert reconcile(world, record).status_code == 429


def test_timeout_after_initiation_never_retries_or_releases(world, provider):
    provider.error = TimeoutError('private-provider-secret')
    permit, request, preview, record = execution(world, provider)
    assert record['state'] == 'reconciliation_required'
    assert record['external_invoice_id'] is None
    assert record['error_code'] == 'outcome_uncertain'
    assert 'private-provider-secret' not in json.dumps(record)
    assert execute(world, preview).status_code == 409
    assert world.action(request, 'cancel').status_code == 409
    assert reconcile(world, record).json()['error_code'] == 'invoice_identity_unknown'
    assert world.summary(permit)['active_reservations_cents'] == 800
    assert provider.buy_calls == 1


def test_revocation_does_not_release_uncertain_checkout(world, provider):
    provider.error = ProviderError('PAYMENT_UNCERTAIN')
    permit, request, _, _ = execution(world, provider)
    revoked = world.client.post(f"/api/permits/{permit['id']}/revoke", headers=world.owner).json()
    assert revoked['status'] == 'revoked'
    assert revoked['spending']['active_reservations_cents'] == 800
    assert world.action(request, 'cancel', world.agent).status_code == 409
    for method in ['mark_failed', 'mark_fulfilled']:
        with pytest.raises(DomainError):
            with spending_service(world.engine) as svc:
                getattr(svc, method)(request['id'])


@pytest.mark.parametrize('status,orders,expected', [
    ('payment_detected', ['created'], 'awaiting_payment'),
    ('payment_confirmed', ['processing'], 'paid'),
    ('pending', ['processing'], 'paid'),
    ('blocked', ['created'], 'reconciliation_required'),
    ('payment_error', ['failed'], 'reconciliation_required'),
    ('denied', ['failed'], 'reconciliation_required'),
    ('complete', ['processing'], 'reconciliation_required'),
])
def test_nonterminal_invoice_states_hold_reservation(world, provider, status, orders, expected):
    permit, _, _, record = execution(world, provider)
    provider.observation = provider.observation.model_copy(update={'invoice_status': status, 'order_statuses': orders})
    assert reconcile(world, record).json()['state'] == expected
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_delivery_success_becomes_spent_exactly_once(world, provider):
    permit, _, _, record = execution(world, provider)
    provider.observation = provider.observation.model_copy(update={'invoice_status': 'complete', 'order_statuses': ['delivered']})
    assert reconcile(world, record).json()['state'] == 'delivered'
    assert reconcile(world, record).json()['state'] == 'delivered'
    assert world.summary(permit) == dict(fulfilled_spend_cents=800, active_reservations_cents=0, remaining_cents=200)


def test_only_verified_refund_releases_failure(world, provider):
    permit, _, _, record = execution(world, provider)
    provider.observation = provider.observation.model_copy(update={'invoice_status': 'payment_error', 'order_statuses': ['failed']})
    assert reconcile(world, record).json()['state'] == 'reconciliation_required'
    assert world.summary(permit)['active_reservations_cents'] == 800
    allow_next_poll(world, record)
    provider.observation = provider.observation.model_copy(update={'order_statuses': ['refunded']})
    assert reconcile(world, record).json()['state'] == 'failed'
    assert world.summary(permit)['remaining_cents'] == 1000
    assert reconcile(world, record).json()['state'] == 'failed'


@pytest.mark.parametrize('changes', [
    {'product_ids': ['wrong-product']}, {'invoice_id': 'wrong-invoice'},
    {'order_statuses': []}, {'product_ids': ['catalog-shop', 'catalog-shop'], 'order_statuses': ['delivered', 'delivered']},
])
def test_invoice_binding_mismatches_never_settle(world, provider, changes):
    permit, _, _, record = execution(world, provider)
    provider.observation = provider.observation.model_copy(update={'invoice_status': 'complete', 'order_statuses': ['delivered'], **changes})
    assert reconcile(world, record).json()['state'] == 'reconciliation_required'
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_recipient_bound_privately_to_preparation_and_owner_confirmation(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    provider.product.recipient_type = 'phone_number'
    _, request = purchase(world)
    assert prepare(world, request).json()['blocker'] == 'recipient_required'
    assert prepare(world, request, recipient='not-a-phone').json()['blocker'] == 'invalid_recipient'
    recipient = '+447911123456'
    preview = prepare(world, request, recipient=recipient).json()
    assert preview['state'] == 'ready'
    assert recipient not in json.dumps(preview)
    with Session(world.engine) as session:
        stored = session.get(PurchasePreview, preview['id'])
        assert stored.recipient_digest != recipient
        assert recipient not in json.dumps(stored.product_snapshot)
    assert execute(world, preview, recipient='+447911123457').status_code == 409
    assert execute(world, preview, recipient=recipient).json()['state'] == 'invoice_created'


def test_concurrent_confirmation_has_one_execution(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    _, request = purchase(world)
    preview = prepare(world, request).json()
    barrier = Barrier(2)

    def confirm(_):
        barrier.wait(timeout=10)
        return execute(world, preview).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(confirm, range(2))) == [200, 409]
    assert provider.buy_calls == 1


# Wire fixtures below use ONLY documented fields. They exercise protocol and
# conservative whitelisting, not an authenticated production schema capture.
def mcp_response(request, payload, *, toon=False, sse=False, error=False):
    rpc = json.loads(request.content)
    text = toon_format.dumps(payload) if toon else json.dumps(payload)
    body = {'jsonrpc': '2.0', 'id': rpc['id'], 'result': {'isError': error, 'content': [{'type': 'text', 'text': text}]}}
    if sse:
        return httpx.Response(200, text='event: message\ndata: ' + json.dumps(body) + '\n\n', headers={'content-type': 'text/event-stream'})
    return httpx.Response(200, json=body)


def client_settings(**overrides):
    return Settings(_env_file=None, bitrefill_api_key=token_urlsafe(32), **overrides)


@pytest.mark.parametrize('toon,sse', [(False, False), (True, False), (True, True)])
def test_mcp_search_protocol_and_whitelist(toon, sse):
    config = client_settings()
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers['authorization'] == f'Bearer {config.bitrefill_api_key.get_secret_value()}'
        assert request.headers['accept'] == 'application/json, text/event-stream'
        assert str(request.url) == 'https://api.bitrefill.com/mcp'
        rpc = json.loads(request.content)
        assert rpc['params']['name'] == 'search-products'
        assert rpc['params']['arguments']['intent'] == 'Find a gift'
        return mcp_response(request, {'products': [{'id': 'catalog-shop', 'name': 'Shop',
            'redemption_info': {'code': 'NEVER-EXPOSE'}, 'invoice_access_token': 'PRIVATE'}]}, toon=toon, sse=sse)
    client = BitrefillClient(config, httpx.MockTransport(handle))
    products = client.search('Shop', 'Find a gift')
    assert products[0].id == 'catalog-shop'
    assert 'NEVER-EXPOSE' not in str(products)
    assert 'PRIVATE' not in str(products)
    assert len(calls) == 1


def test_mcp_details_denomination_is_not_a_quote():
    def handle(request):
        assert json.loads(request.content)['params']['arguments']['currency'] == 'USD'
        return mcp_response(request, {'id': 'catalog-shop', 'currency': 'USD', 'type': 'gift_card',
            'packages': [{'package_id': 'catalog-shop<&>8', 'package_value': '8'}],
            'recipient_type': 'email', 'price': '8.00', 'invoice_access_token': 'PRIVATE'})
    client = BitrefillClient(client_settings(), httpx.MockTransport(handle))
    product = client.details('catalog-shop')
    assert product.denominations[0].package_value == '8'
    assert product.recipient_type == 'email'
    assert product.quoted_total_cents is None
    assert product.available is None
    with pytest.raises(ProviderError, match='Bitrefill') as exc:
        client.quote(product, '8', None)
    assert exc.value.code == 'quote_contract_unverified'


def test_mcp_invoice_response_filters_codes_and_tokens():
    def handle(request):
        return mcp_response(request, {'invoice_id': 'invoice-1', 'invoice_status': 'complete',
            'orders': [{'status': 'delivered', 'product': {'id': 'catalog-shop'},
                        'redemption_info': {'code': 'PRIVATE'}, 'esim_install_link': 'SECRET'}],
            'invoice_access_token': 'TOKEN', 'payment_link': 'PRIVATE-LINK'})
    client = BitrefillClient(client_settings(), httpx.MockTransport(handle))
    observation = client.invoice('invoice-1')
    assert observation.invoice_status == 'complete'
    assert all(secret not in observation.model_dump_json() for secret in ['PRIVATE', 'SECRET', 'TOKEN'])


@pytest.mark.parametrize('status,code', [(401, 'credentials_rejected'), (429, 'rate_limited'), (500, 'http_error')])
def test_http_errors_are_sanitized(status, code, caplog):
    config = client_settings()
    client = BitrefillClient(config, httpx.MockTransport(lambda request: httpx.Response(status, text='PRIVATE-TOKEN')))
    with pytest.raises(ProviderError) as exc:
        client.details('catalog-shop')
    assert exc.value.code == code
    assert 'PRIVATE-TOKEN' not in caplog.text
    assert config.bitrefill_api_key.get_secret_value() not in caplog.text


def test_missing_credentials_fails_before_network():
    client = BitrefillClient(Settings(_env_file=None), httpx.MockTransport(lambda _: pytest.fail('Network attempted')))
    with pytest.raises(ProviderError) as exc:
        client.details('catalog-shop')
    assert exc.value.code == 'credentials_missing'


def test_read_timeout_retries_once_with_sanitized_error():
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('PRIVATE')
    client = BitrefillClient(client_settings(), httpx.MockTransport(handle))
    with pytest.raises(ProviderError) as exc:
        client.details('catalog-shop')
    assert exc.value.code == 'timeout'
    assert len(calls) == 2
    assert 'PRIVATE' not in str(exc.value)


def test_transient_service_error_retries_only_reads():
    calls = []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return mcp_response(request, {'code': 'SERVICE_UNAVAILABLE', 'error': 'PRIVATE'}, error=True)
        return mcp_response(request, {'id': 'catalog-shop'})
    client = BitrefillClient(client_settings(), httpx.MockTransport(handle))
    assert client.details('catalog-shop').id == 'catalog-shop'
    assert len(calls) == 2


@pytest.mark.parametrize('live', [False, True])
def test_real_adapter_never_dispatches_buy_even_if_switch_enabled(live):
    config = client_settings()
    config.bitrefill_live_purchases_enabled = live
    client = BitrefillClient(config, httpx.MockTransport(lambda _: pytest.fail('buy-products must never dispatch')))
    product = Product(id='catalog-shop')
    quote = Quote(product=product, denomination='8', total_cents=800, currency='USD',
                  payment_method='fiat_card', expires_at=utcnow() + timedelta(minutes=1))
    with pytest.raises(ProviderError) as exc:
        client.create_invoice(quote, None)
    assert exc.value.code == ('checkout_contract_unverified' if live else 'live_purchases_disabled')


def test_live_adapter_persists_blocked_preview_instead_of_inventing_price(world):
    _, request = purchase(world)
    provider = BitrefillClient(client_settings(), httpx.MockTransport(lambda req: mcp_response(req, {
        'id': 'catalog-shop', 'type': 'gift_card', 'currency': 'USD',
        'packages': [{'package_value': '8'}],
    })))
    world.client.app.state.bitrefill_provider = provider
    preview = prepare(world, request).json()
    assert preview['state'] == 'blocked'
    assert preview['blocker'] == 'quote_contract_unverified'
    assert preview['amount_cents'] is None


def test_provider_error_endpoint_does_not_leak_credentials(world):
    world.client.app.state.bitrefill_provider = BitrefillClient(Settings(_env_file=None))
    response = world.client.get('/api/bitrefill/products/catalog-shop', headers=world.agent)
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'credentials_missing'


def test_budget_and_expiry_rechecked_after_fresh_provider_read(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    original = provider.details
    def expire_during_read(product_id):
        result = original(product_id)
        world.expire(permit)
        return result
    provider.details = expire_during_read
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_revocation_during_read_prevents_initiation(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    original = provider.details
    def revoke_during_read(product_id):
        result = original(product_id)
        with spending_service(world.engine) as svc:
            svc.revoke(permit['id'], world.settings.dev_owner_id)
        return result
    provider.details = revoke_during_read
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0
    assert world.summary(permit)['active_reservations_cents'] == 0


def test_changed_budget_limit_cannot_execute(world, provider):
    world.settings.bitrefill_live_purchases_enabled = True
    permit, request = purchase(world)
    preview = prepare(world, request).json()
    with Session(world.engine) as session:
        session.get(Permit, permit['id']).per_purchase_limit_cents = 700
        session.commit()
    assert execute(world, preview).status_code == 409
    assert provider.buy_calls == 0


def test_pending_quote_does_not_reserve_and_approval_still_checks_other_spend(world, provider):
    permit, request = purchase(world, approval_threshold_cents=500)
    assert prepare(world, request).json()['state'] == 'ready'
    other = world.submit(permit, merchant='catalog-shop', category='gift_card', product_id='catalog-shop', amount_cents=500)
    assert other['state'] == 'authorized'
    assert world.action(request, 'approve').json()['denial_reason'] == 'insufficient_budget'
    assert world.summary(permit)['active_reservations_cents'] == 500


def test_unique_invoice_identity_prevents_wrong_invoice_binding(world, provider):
    _, _, _, first = execution(world, provider)
    _, request = purchase(world)
    preview = prepare(world, request).json()
    second = execute(world, preview)
    assert second.status_code == 200
    assert second.json()['state'] == 'reconciliation_required'
    assert second.json()['external_invoice_id'] is None
    assert second.json()['error_code'] == 'invoice_identity_conflict'
    assert first['external_invoice_id'] == 'provider-invoice-1'


def test_non_monotonic_invoice_status_does_not_release(world, provider):
    permit, _, _, record = execution(world, provider)
    provider.observation = provider.observation.model_copy(update={'invoice_status': 'payment_confirmed', 'order_statuses': ['processing']})
    assert reconcile(world, record).json()['state'] == 'paid'
    allow_next_poll(world, record)
    provider.observation = provider.observation.model_copy(update={'invoice_status': 'unpaid', 'order_statuses': ['created']})
    response = reconcile(world, record).json()
    assert response['state'] == 'reconciliation_required'
    assert response['payment_status'] == 'payment_confirmed'
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_lookup_timeout_keeps_reservation(world, provider):
    permit, _, _, record = execution(world, provider)
    def timeout(invoice_id):
        raise ProviderError('timeout', 504)
    provider.invoice = timeout
    response = reconcile(world, record).json()
    assert response['error_code'] == 'invoice_lookup_failed'
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_other_owner_cannot_read_preview_or_execution(world, provider):
    permit, _, preview, record = execution(world, provider)
    with Session(world.engine) as session:
        session.get(Permit, permit['id']).owner_id = 'other-owner'
        session.commit()
    assert world.client.get(f"/api/bitrefill/purchase-previews/{preview['id']}", headers=world.owner).status_code == 404
    assert world.client.get(f"/api/bitrefill/executions/{record['id']}", headers=world.owner).status_code == 404
    assert reconcile(world, record).status_code == 404


@pytest.mark.parametrize('field', ['amount_cents', 'currency', 'merchant', 'category', 'authorized'])
def test_preparation_cannot_accept_agent_price_or_authorization_overrides(world, provider, field):
    _, request = purchase(world)
    assert prepare(world, request, **{field: 'untrusted'}).status_code == 422
    assert provider.buy_calls == 0


@pytest.mark.parametrize('raw', [{'unexpected': []}, [], {'id': 'wrong-id'}, {'id': 'catalog-shop', 'packages': 'invalid'}])
def test_unknown_detail_contract_is_rejected(raw):
    client = BitrefillClient(client_settings(), httpx.MockTransport(lambda request: mcp_response(request, raw)))
    with pytest.raises(ProviderError):
        client.details('catalog-shop')


def test_tool_payment_uncertain_is_never_retried(caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return mcp_response(request, {'code': 'PAYMENT_UNCERTAIN', 'error': 'PRIVATE',
                                    'details': {'invoice_access_token': 'SECRET'}}, error=True)
    client = BitrefillClient(client_settings(), httpx.MockTransport(handle))
    with pytest.raises(ProviderError) as exc:
        client.details('catalog-shop')
    assert exc.value.code == 'PAYMENT_UNCERTAIN'
    assert len(calls) == 1
    assert all(secret not in caplog.text for secret in ['PRIVATE', 'SECRET'])


def test_wrong_rpc_identity_and_oversized_responses_fail_closed():
    for response in [httpx.Response(200, json={'jsonrpc': '2.0', 'id': 'wrong', 'result': {}}),
                     httpx.Response(200, content=b'x' * 1_000_001)]:
        client = BitrefillClient(client_settings(), httpx.MockTransport(lambda _: response))
        with pytest.raises(ProviderError):
            client.details('catalog-shop')


def test_bitrefill_environment_switch_and_secret_masking(monkeypatch):
    key = token_urlsafe(32)
    monkeypatch.setenv('BITREFILL_API_KEY', key)
    monkeypatch.setenv('BITREFILL_LIVE_PURCHASES_ENABLED', 'true')
    config = Settings(_env_file=None)
    assert config.bitrefill_api_key.get_secret_value() == key
    assert config.bitrefill_live_purchases_enabled is True
    assert key not in repr(config)
