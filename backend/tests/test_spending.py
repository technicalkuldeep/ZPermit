from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Base, create_database_engine
from app.main import create_app
from app.models.spending import Permit, PurchaseRequest
from app.schemas.spending import PurchaseCreate
from app.services.spending import DomainError, spending_service


@pytest.fixture
def world(tmp_path):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'spending.db'}",
                        dev_owner_credential=token_urlsafe(32), dev_agent_credential=token_urlsafe(32))
    app = create_app(settings)
    Base.metadata.create_all(app.state.database_engine)
    with TestClient(app) as client:
        yield World(client, app.state.database_engine, settings)


class World:
    def __init__(self, client, engine, settings):
        self.client, self.engine, self.settings = client, engine, settings
        self.owner = {'Authorization': f'Bearer {settings.dev_owner_credential.get_secret_value()}'}
        self.agent = {'Authorization': f'Bearer {settings.dev_agent_credential.get_secret_value()}'}

    def permit(self, **overrides):
        data = dict(agent_id='shopping-agent', name='Supplies', currency='USD', total_limit_cents=1000,
                    per_purchase_limit_cents=1000, allowed_merchants=['shop'], allowed_categories=['supplies'],
                    expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        data.update(overrides)
        response = self.client.post('/api/permits', json=data, headers=self.owner)
        assert response.status_code == 201, response.text
        return response.json()

    def proposal(self, permit, **overrides):
        data = dict(permit_id=permit['id'], agent_id='shopping-agent', merchant='shop', category='supplies',
                    product_id='paper', amount_cents=800, currency='USD', external_request_id=str(uuid4()))
        data.update(overrides)
        return data

    def submit(self, permit, **overrides):
        response = self.client.post('/api/purchase-requests', json=self.proposal(permit, **overrides), headers=self.agent)
        assert response.status_code == 200, response.text
        return response.json()

    def action(self, purchase, action, headers=None):
        return self.client.post(f"/api/purchase-requests/{purchase['id']}/{action}",
                                headers=self.owner if headers is None else headers)

    def summary(self, permit):
        response = self.client.get(f"/api/permits/{permit['id']}", headers=self.owner)
        assert response.status_code == 200
        return response.json()['spending']

    def expire(self, permit):
        with Session(self.engine) as session:
            session.get(Permit, permit['id']).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()


def test_normal_authorization_and_fulfillment(world):
    permit = world.permit()
    purchase = world.submit(permit)
    assert purchase['state'] == 'authorized'
    assert purchase['denial_reason'] is None
    assert purchase['created_at'].endswith('Z')
    assert world.summary(permit) == dict(fulfilled_spend_cents=0, active_reservations_cents=800, remaining_cents=200)
    with spending_service(world.engine) as svc:
        assert svc.mark_fulfilled(purchase['id']).state == 'fulfilled'
    assert world.summary(permit) == dict(fulfilled_spend_cents=800, active_reservations_cents=0, remaining_cents=200)
    assert world.submit(permit, amount_cents=201)['denial_reason'] == 'insufficient_budget'


def test_pending_is_not_reserved_then_approval_reserves(world):
    permit = world.permit(approval_threshold_cents=500)
    purchase = world.submit(permit)
    assert purchase['state'] == 'pending_approval'
    assert world.summary(permit)['remaining_cents'] == 1000
    result = world.action(purchase, 'approve')
    assert result.status_code == 200
    assert result.json()['state'] == 'authorized'
    assert world.summary(permit)['remaining_cents'] == 200
    assert world.action(purchase, 'approve').status_code == 409


@pytest.mark.parametrize('changes,reason', [
    ({'amount_cents': 0}, 'invalid_amount'), ({'amount_cents': -1}, 'invalid_amount'),
    ({'amount_cents': 1001}, 'per_purchase_limit_exceeded'), ({'currency': 'EUR'}, 'unsupported_currency'),
    ({'merchant': 'shop-extra'}, 'merchant_not_allowed'), ({'merchant': 'other'}, 'merchant_not_allowed'),
    ({'category': 'supplies-extra'}, 'category_not_allowed'), ({'category': 'other'}, 'category_not_allowed'),
])
def test_policy_denials(world, changes, reason):
    permit = world.permit()
    purchase = world.submit(permit, **changes)
    assert purchase['state'] == 'denied'
    assert purchase['denial_reason'] == reason
    assert world.summary(permit)['remaining_cents'] == 1000


def test_exact_normalized_identifiers(world):
    permit = world.permit(allowed_merchants=[' SHOP ', 'shop'], allowed_categories=[' SUPPLIES '])
    assert permit['allowed_merchants'] == ['shop']
    assert world.submit(permit, merchant=' Shop ', category=' SUPPLIES ')['state'] == 'authorized'


def test_expired_and_revoked_denials(world):
    expired = world.permit()
    world.expire(expired)
    assert world.submit(expired)['denial_reason'] == 'permit_expired'
    revoked = world.permit()
    response = world.client.post(f"/api/permits/{revoked['id']}/revoke", headers=world.owner)
    assert response.json()['status'] == 'revoked'
    assert world.submit(revoked)['denial_reason'] == 'permit_revoked'


def test_mismatched_agent_and_credential_binding(world):
    permit = world.permit(agent_id='different-agent')
    assert world.submit(permit)['denial_reason'] == 'agent_mismatch'
    response = world.client.post('/api/purchase-requests', json=world.proposal(permit, agent_id='different-agent'), headers=world.agent)
    assert response.status_code == 403


def test_idempotent_retry_does_not_reserve_twice(world):
    permit = world.permit()
    data = world.proposal(permit)
    first = world.client.post('/api/purchase-requests', json=data, headers=world.agent)
    second = world.client.post('/api/purchase-requests', json=data, headers=world.agent)
    assert first.json() == second.json()
    assert world.summary(permit)['remaining_cents'] == 200
    world.action(first.json(), 'cancel')
    retry = world.client.post('/api/purchase-requests', json=data, headers=world.agent)
    assert retry.json()['state'] == 'cancelled'
    assert world.summary(permit)['remaining_cents'] == 1000


@pytest.mark.parametrize('field,value', [('amount_cents', 700), ('product_id', 'pens'), ('currency', 'EUR'),
                                        ('merchant', 'other'), ('category', 'other'), ('permit_id', str(uuid4()))])
def test_conflicting_retry(world, field, value):
    permit = world.permit()
    data = world.proposal(permit)
    assert world.client.post('/api/purchase-requests', json=data, headers=world.agent).status_code == 200
    data[field] = value
    assert world.client.post('/api/purchase-requests', json=data, headers=world.agent).status_code == 409
    assert world.summary(permit)['remaining_cents'] == 200


@pytest.mark.parametrize('release', ['cancel', 'fail'])
def test_reservation_release(world, release):
    permit = world.permit()
    purchase = world.submit(permit)
    if release == 'cancel':
        assert world.action(purchase, 'cancel', world.agent).json()['state'] == 'cancelled'
    else:
        with spending_service(world.engine) as svc:
            assert svc.mark_failed(purchase['id']).state == 'failed'
    assert world.summary(permit)['remaining_cents'] == 1000
    assert world.submit(permit)['state'] == 'authorized'


def test_rejection_and_pending_cancellation(world):
    permit = world.permit(approval_threshold_cents=0)
    rejected = world.submit(permit)
    assert world.action(rejected, 'reject').json()['state'] == 'rejected'
    cancelled = world.submit(permit)
    assert world.action(cancelled, 'cancel').json()['state'] == 'cancelled'
    assert world.summary(permit)['remaining_cents'] == 1000
    assert world.action(rejected, 'approve').status_code == 409
    assert world.action(cancelled, 'approve').status_code == 409


def test_approval_rechecks_budget(world):
    permit = world.permit(approval_threshold_cents=500)
    first, second = world.submit(permit), world.submit(permit)
    assert world.action(first, 'approve').json()['state'] == 'authorized'
    denied = world.action(second, 'approve').json()
    assert denied['state'] == 'denied'
    assert denied['denial_reason'] == 'insufficient_budget'
    assert world.summary(permit)['remaining_cents'] == 200


def test_approval_rechecks_expiration(world):
    permit = world.permit(approval_threshold_cents=0)
    purchase = world.submit(permit)
    world.expire(permit)
    result = world.action(purchase, 'approve').json()
    assert result['state'] == 'denied'
    assert result['denial_reason'] == 'permit_expired'
    assert world.summary(permit)['remaining_cents'] == 1000


def test_approval_rechecks_active_permit(world):
    permit = world.permit(approval_threshold_cents=0)
    purchase = world.submit(permit)
    with Session(world.engine) as session:
        session.get(Permit, permit['id']).status = 'revoked'
        session.commit()
    assert world.action(purchase, 'approve').json()['denial_reason'] == 'permit_revoked'
    assert world.summary(permit)['remaining_cents'] == 1000


def test_revocation_cancels_outstanding_and_preserves_spent(world):
    permit = world.permit(approval_threshold_cents=500)
    spent = world.submit(permit, amount_cents=100)
    with spending_service(world.engine) as svc:
        svc.mark_fulfilled(spent['id'])
    reserved, pending = world.submit(permit, amount_cents=100), world.submit(permit)
    response = world.client.post(f"/api/permits/{permit['id']}/revoke", headers=world.owner)
    assert response.json()['spending'] == dict(fulfilled_spend_cents=100, active_reservations_cents=0, remaining_cents=900)
    for purchase in [reserved, pending]:
        result = world.client.get(f"/api/purchase-requests/{purchase['id']}", headers=world.agent)
        assert result.json()['state'] == 'cancelled'
        assert world.action(purchase, 'approve').status_code == 409


@pytest.mark.parametrize('terminal', ['fulfilled', 'failed', 'cancelled', 'denied', 'rejected'])
def test_forbidden_terminal_transitions(world, terminal):
    permit = world.permit(approval_threshold_cents=0 if terminal == 'rejected' else None)
    purchase = world.submit(permit, amount_cents=0 if terminal == 'denied' else 800)
    if terminal in {'rejected', 'cancelled'}:
        world.action(purchase, 'reject' if terminal == 'rejected' else 'cancel')
    elif terminal in {'fulfilled', 'failed'}:
        with spending_service(world.engine) as svc:
            getattr(svc, 'mark_' + terminal)(purchase['id'])
    for action in ['approve', 'reject', 'cancel']:
        assert world.action(purchase, action).status_code == 409
    for action in ['mark_fulfilled', 'mark_failed']:
        with pytest.raises(DomainError) as error:
            with spending_service(world.engine) as svc:
                getattr(svc, action)(purchase['id'])
        assert error.value.status_code == 409
    assert world.summary(permit)['remaining_cents'] >= 0


def test_pending_cannot_be_fulfilled_or_failed(world):
    purchase = world.submit(world.permit(approval_threshold_cents=0))
    for action in ['mark_fulfilled', 'mark_failed']:
        with pytest.raises(DomainError):
            with spending_service(world.engine) as svc:
                getattr(svc, action)(purchase['id'])


@pytest.mark.parametrize('action', ['approve', 'reject'])
def test_agent_cannot_make_owner_decisions(world, action):
    purchase = world.submit(world.permit(approval_threshold_cents=0))
    assert world.action(purchase, action, world.agent).status_code == 403


def test_agent_cannot_access_owner_permit_routes(world):
    permit = world.permit()
    for path in ['/api/permits', f"/api/permits/{permit['id']}"]:
        assert world.client.get(path, headers=world.agent).status_code == 403
    assert world.client.post(f"/api/permits/{permit['id']}/revoke", headers=world.agent).status_code == 403
    assert world.client.post('/api/permits', json={}, headers=world.agent).status_code == 403
    assert world.client.post('/api/purchase-requests', json=world.proposal(permit), headers=world.owner).status_code == 403


@pytest.mark.parametrize('flag', ['approved', 'authorized', 'fulfilled', 'spent', 'state', 'owner_id'])
def test_agent_cannot_inject_authorization_fields(world, flag):
    permit = world.permit()
    data = world.proposal(permit)
    data[flag] = True
    assert world.client.post('/api/purchase-requests', json=data, headers=world.agent).status_code == 422
    assert world.summary(permit)['remaining_cents'] == 1000


@pytest.mark.parametrize('amount', [1.5, '800', True, None, 10**13])
def test_rejects_non_integer_or_unbounded_money(world, amount):
    permit = world.permit()
    data = world.proposal(permit, amount_cents=amount)
    assert world.client.post('/api/purchase-requests', json=data, headers=world.agent).status_code == 422


def test_credentials_fail_closed_and_do_not_leak(world):
    for headers in [{}, {'Authorization': 'Bearer invalid'}]:
        assert world.client.get('/api/permits', headers=headers).status_code == 401
    assert world.settings.dev_owner_credential.get_secret_value() not in repr(world.settings)
    for owner, agent in [(None, None), (token_urlsafe(32), None), (None, token_urlsafe(32)), ('', ''), ('same', 'same')]:
        config = Settings(_env_file=None, dev_owner_credential=owner, dev_agent_credential=agent)
        with TestClient(create_app(config)) as client:
            assert client.get('/api/permits', headers=world.owner).status_code == 503
            assert client.post('/api/purchase-requests', json={}, headers=world.agent).status_code == 503


def test_owner_boundary_and_visibility(world):
    permit = world.permit()
    assert permit['owner_id'] == world.settings.dev_owner_id
    assert len(world.client.get('/api/permits', headers=world.owner).json()) == 1
    purchase = world.submit(permit)
    with Session(world.engine) as session:
        session.get(Permit, permit['id']).owner_id = 'another-owner'
        session.get(PurchaseRequest, purchase['id']).agent_id = 'another-agent'
        session.commit()
    assert world.client.get('/api/permits', headers=world.owner).json() == []
    assert world.client.get(f"/api/permits/{permit['id']}", headers=world.owner).status_code == 404
    assert world.client.post(f"/api/permits/{permit['id']}/revoke", headers=world.owner).status_code == 404
    assert world.action(purchase, 'approve').status_code == 404
    for headers in [world.owner, world.agent]:
        assert world.client.get(f"/api/purchase-requests/{purchase['id']}", headers=headers).status_code == 404
        assert world.action(purchase, 'cancel', headers).status_code == 404


@pytest.mark.parametrize('changes', [
    {'currency': 'EUR'}, {'owner_id': 'spoofed'}, {'total_limit_cents': 0}, {'total_limit_cents': 1.5},
    {'per_purchase_limit_cents': 1001}, {'approval_threshold_cents': -1}, {'allowed_merchants': []},
    {'allowed_categories': ['*']}, {'allowed_merchants': ['shop/path']},
    {'expires_at': '2030-01-01T00:00:00'}, {'expires_at': '2000-01-01T00:00:00Z'},
])
def test_invalid_permits(world, changes):
    data = dict(agent_id='shopping-agent', name='Supplies', total_limit_cents=1000,
                per_purchase_limit_cents=1000, allowed_merchants=['shop'], allowed_categories=['supplies'],
                expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    data.update(changes)
    assert world.client.post('/api/permits', json=data, headers=world.owner).status_code == 422


def test_threshold_and_limits_are_inclusive(world):
    permit = world.permit(approval_threshold_cents=1000)
    assert world.submit(permit, amount_cents=1000)['state'] == 'authorized'
    assert world.summary(permit)['remaining_cents'] == 0


def test_utc_round_trip(world):
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).astimezone(timezone(timedelta(hours=5)))
    permit = world.permit(expires_at=expiry.isoformat())
    assert datetime.fromisoformat(permit['expires_at']) == expiry
    assert permit['expires_at'].endswith('Z')


@pytest.mark.parametrize('approval', [False, True])
def test_concurrent_budget_contention(world, approval):
    permit = world.permit(approval_threshold_cents=0 if approval else None)
    barrier = Barrier(2)
    requests = [world.proposal(permit), world.proposal(permit)]
    if approval:
        purchases = [world.client.post('/api/purchase-requests', json=data, headers=world.agent).json() for data in requests]

    def compete(index):
        engine = create_database_engine(world.settings.database_url)
        try:
            barrier.wait(timeout=10)
            with spending_service(engine) as svc:
                if approval:
                    return svc.approve(purchases[index]['id'], world.settings.dev_owner_id).state
                return svc.submit(PurchaseCreate(**requests[index]), world.settings.dev_agent_id).state
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        states = list(executor.map(compete, range(2)))
    assert sorted(states) == ['authorized', 'denied']
    assert world.summary(permit) == dict(fulfilled_spend_cents=0, active_reservations_cents=800, remaining_cents=200)


def test_concurrent_identical_retry(world):
    permit = world.permit()
    data = PurchaseCreate(**world.proposal(permit))
    barrier = Barrier(2)

    def submit(_):
        barrier.wait(timeout=10)
        with spending_service(world.engine) as svc:
            return svc.submit(data, world.settings.dev_agent_id).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(submit, range(2)))
    assert ids[0] == ids[1]
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_transaction_rollback_on_failure(world):
    permit = world.permit()
    with pytest.raises(RuntimeError):
        with spending_service(world.engine) as svc:
            svc.submit(PurchaseCreate(**world.proposal(permit)), world.settings.dev_agent_id)
            raise RuntimeError('abort')
    assert world.summary(permit)['remaining_cents'] == 1000


def test_database_constraints_and_persistence(world):
    permit = world.permit()
    purchase = world.submit(permit)
    engine = create_database_engine(world.settings.database_url)
    try:
        with spending_service(engine) as svc:
            assert svc.purchase(purchase['id']).state == 'authorized'
            assert svc.permit(permit['id']).allowed_merchants == ['shop']
        with engine.connect() as connection:
            assert connection.execute(text('PRAGMA foreign_keys')).scalar() == 1
    finally:
        engine.dispose()


def test_settlement_routes_do_not_exist(world):
    purchase = world.submit(world.permit())
    for action in ['fulfill', 'fulfilled', 'fail', 'mark_fulfilled', 'mark_failed']:
        assert world.action(purchase, action, world.agent).status_code == 404


@pytest.mark.parametrize('amount,expected', [(0, 'denied'), (800, 'pending_approval')])
def test_retry_preserves_denied_and_pending_decisions(world, amount, expected):
    permit = world.permit(approval_threshold_cents=0)
    data = world.proposal(permit, amount_cents=amount)
    first = world.client.post('/api/purchase-requests', json=data, headers=world.agent)
    second = world.client.post('/api/purchase-requests', json=data, headers=world.agent)
    assert first.json() == second.json()
    assert second.json()['state'] == expected
    assert world.summary(permit)['remaining_cents'] == 1000


def test_idempotency_uses_normalized_identifiers(world):
    permit = world.permit()
    data = world.proposal(permit, merchant=' SHOP ', category=' SUPPLIES ')
    first = world.client.post('/api/purchase-requests', json=data, headers=world.agent).json()
    data.update(merchant='shop', category='supplies')
    assert world.client.post('/api/purchase-requests', json=data, headers=world.agent).json() == first


def test_concurrent_double_fulfillment(world):
    permit = world.permit()
    purchase = world.submit(permit)
    barrier = Barrier(2)

    def settle(_):
        barrier.wait(timeout=10)
        try:
            with spending_service(world.engine) as svc:
                return svc.mark_fulfilled(purchase['id']).state
        except DomainError as exc:
            return str(exc.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(settle, range(2))) == ['409', 'fulfilled']
    assert world.summary(permit) == dict(fulfilled_spend_cents=800, active_reservations_cents=0, remaining_cents=200)


def test_database_rejects_invalid_active_reservation(world):
    from sqlalchemy.exc import IntegrityError

    permit = world.permit()
    purchase = world.submit(permit)
    with pytest.raises(IntegrityError):
        with world.engine.begin() as connection:
            connection.execute(text('UPDATE purchase_requests SET amount_cents = -1 WHERE id = :id'), {'id': purchase['id']})
    assert world.summary(permit)['active_reservations_cents'] == 800


def test_missing_schema_returns_safe_service_unavailable(tmp_path):
    config = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'uninitialized.db'}",
                      dev_owner_credential=token_urlsafe(32), dev_agent_credential=token_urlsafe(32))
    with TestClient(create_app(config)) as client:
        response = client.get('/api/permits', headers={
            'Authorization': f'Bearer {config.dev_owner_credential.get_secret_value()}',
        })
        assert response.status_code == 503
        assert response.json() == {'detail': 'Database unavailable; retry later'}
        assert client.get('/health').status_code == 200
