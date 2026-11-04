"""TEST DOUBLES ONLY. No real receiving address, signing, send, or chain claims.
The checksum-invalid address and synthetic txid are accepted only by test doubles.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from PIL import Image
import pytest
import qrcode
from sqlalchemy.orm import Session

from test_public_testnet import ADDRESS, TXID, block_live, client
from test_spending import world
from app.core.security import Identity
from app.integrations.zcash import ZcashError
from app.models.mobile_payment import MobilePaymentRequest, MobilePaymentEvidence
from app.models.public_testnet import PublicTransactionObservation
from app.schemas.mobile_payment import MobilePaymentInput
from app.services.mobile_payment import MobilePaymentWorkflow

BASE = '/api/zcash/mobile/payment-requests'


@pytest.fixture
def mobile(world, client):
    world.client.app.state.public_testnet = client
    world.public = client
    world.wallet = Mock()
    world.client.app.state.zcash_wallet = world.wallet
    return world


def prepare(w, **changes):
    data = dict(request_key='phone-test-1', destination=ADDRESS, amount_zatoshis=100000)
    data.update(changes)
    return w.client.post(BASE, headers=w.owner, json=data)


def attach(w, p, **changes):
    data = dict(request_key='phone-evidence-1', txid=TXID)
    data.update(changes)
    return w.client.post(f"{BASE}/{p['id']}/evidence", headers=w.owner, json=data)


def test_exact_zip321_amount_memo_and_idempotency(mobile):
    w = mobile
    memo = 'Phone demo: café 📱 & ? ='
    response = prepare(w, memo=memo)
    assert response.status_code == 201, response.text
    p = response.json()
    uri = urlsplit(p['payment_uri'])
    assert uri.scheme == 'zcash' and uri.path == ADDRESS and not uri.netloc
    fields = parse_qs(uri.query)
    assert fields['amount'] == ['0.001']
    encoded = fields['memo'][0]
    assert '=' not in encoded and '+' not in encoded and '/' not in encoded
    assert base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode() == memo
    assert p['owner_wallet_review_required'] and not p['backend_broadcast']
    assert p['wallet_link_support'] == 'unverified_for_installed_version'
    assert response.headers['cache-control'] == 'no-store'
    assert prepare(w, memo=memo).json()['id'] == p['id']
    assert prepare(w, memo='changed').status_code == 409
    assert prepare(w, memo=memo, amount_zatoshis=1).status_code == 409
    assert w.client.get(f"{BASE}/{p['id']}", headers=w.owner).json() == p
    w.wallet.send.assert_not_called()
    w.public.read.assert_not_called()


@pytest.mark.parametrize('zatoshis,decimal', [(1, '0.00000001'), (10, '0.0000001'), (100000000, '1')])
def test_integer_amount_format(mobile, zatoshis, decimal):
    p = prepare(mobile, amount_zatoshis=zatoshis).json()
    assert p['amount_taz'] == decimal and p['payment_uri'].endswith('?amount=' + decimal)
    assert 'memo=' not in p['payment_uri']


@pytest.mark.parametrize('amount', [True, 1.0, '1', 0, -1, 100000001])
def test_strict_bounded_amount(mobile, amount):
    assert prepare(mobile, amount_zatoshis=amount).status_code == 422


def test_memo_utf8_byte_limit(mobile):
    assert prepare(mobile, memo='é' * 256).status_code == 201
    assert prepare(mobile, request_key='large', memo='é' * 257).status_code == 422
    assert prepare(mobile, request_key='ascii', memo='a' * 513).status_code == 422


@pytest.mark.parametrize('field', ['seed_phrase', 'private_key', 'owner_id', 'approved', 'txid', 'purchase_request_id'])
def test_no_secret_or_authorization_inputs(mobile, field):
    assert prepare(mobile, **{field: 'forbidden'}).status_code == 422


def test_rejected_address_cannot_create_request(mobile):
    mobile.public.inspector.address.side_effect = ZcashError('testnet_unified_address_required')
    assert prepare(mobile, destination='u1not-testnet').status_code == 503
    with Session(mobile.engine) as session:
        assert session.query(MobilePaymentRequest).count() == 0


def test_real_png_encodes_only_payment_uri(mobile, monkeypatch):
    p = prepare(mobile, memo='test fixture').json()
    added = []
    original = qrcode.QRCode.add_data
    def capture(self, data, *args, **kwargs):
        added.append(data)
        return original(self, data, *args, **kwargs)
    monkeypatch.setattr(qrcode.QRCode, 'add_data', capture)
    response = mobile.client.get(p['qr_path'], headers=mobile.owner)
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert response.headers['cache-control'] == 'no-store'
    assert added == [p['payment_uri']]
    assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
    image = Image.open(BytesIO(response.content))
    assert image.width == image.height and image.width >= 100
    mobile.wallet.send.assert_not_called()


def test_all_routes_owner_only(mobile):
    p = prepare(mobile).json()
    routes = [('POST', BASE, dict(request_key='x', destination=ADDRESS, amount_zatoshis=1)),
              ('GET', f"{BASE}/{p['id']}", None), ('GET', p['qr_path'], None),
              ('POST', f"{BASE}/{p['id']}/evidence", dict(request_key='x', txid=TXID))]
    for method, path, data in routes:
        for headers, status in [(mobile.agent, 403), ({}, 401)]:
            assert mobile.client.request(method, path, headers=headers, json=data).status_code == status


def test_request_owner_visibility(mobile):
    p = prepare(mobile).json()
    with Session(mobile.engine) as session:
        session.get(MobilePaymentRequest, p['id']).owner_id = 'different-owner'
        session.commit()
    assert mobile.client.get(f"{BASE}/{p['id']}", headers=mobile.owner).status_code == 404
    assert mobile.client.get(p['qr_path'], headers=mobile.owner).status_code == 404
    assert attach(mobile, p).status_code == 404
    mobile.public.read.assert_not_called()


def test_mined_evidence_never_proves_private_terms_or_settles_purchase(mobile):
    w = mobile
    permit = w.permit()
    purchase = w.submit(permit)
    before = w.summary(permit)
    p = prepare(w).json()
    response = attach(w, p)
    assert response.status_code == 200, response.text
    r = response.json()
    assert r['association'] == 'owner_reported'
    assert r['observation']['origin'] == 'wallet_initiated_owner_report'
    assert r['observation']['evidence']['verified_mined']
    for key in ['recipient_verified', 'amount_verified', 'memo_verified', 'sender_verified']:
        assert r[key] is False
    assert attach(w, p).json() == r
    assert attach(w, p, request_key='changed-tx', txid='34' * 32).status_code == 409
    request = w.client.get(f"{BASE}/{p['id']}", headers=w.owner).json()
    assert request['observation_id'] == r['observation']['id']
    assert not request['private_payment_details_verified']
    assert request['state'] == 'prepared_for_external_wallet'
    assert w.summary(permit) == before
    assert w.client.get('/api/purchase-requests/' + purchase['id'], headers=w.owner).json()['state'] == 'authorized'
    w.wallet.send.assert_not_called()


def test_existing_evidence_endpoint_can_be_reused(mobile):
    p = prepare(mobile).json()
    data = dict(request_key='phone-evidence-1', txid=TXID)
    existing = mobile.client.post('/api/zcash/public/transactions', json=data, headers=mobile.owner).json()
    assert attach(mobile, p).json()['observation']['id'] == existing['id']


def test_failed_evidence_lookup_creates_no_association(mobile):
    p = prepare(mobile).json()
    mobile.public.transaction = Mock(side_effect=ZcashError('public_testnet_timeout'))
    assert attach(mobile, p).status_code == 503
    assert mobile.client.get(f"{BASE}/{p['id']}", headers=mobile.owner).json()['observation_id'] is None
    with Session(mobile.engine) as session:
        assert session.query(MobilePaymentEvidence).count() == 0
        assert session.query(PublicTransactionObservation).count() == 0


def test_one_observation_cannot_be_attached_to_two_requests(mobile):
    first = prepare(mobile).json()
    attach(mobile, first)
    second = prepare(mobile, request_key='other-payment', amount_zatoshis=1).json()
    assert attach(mobile, second).status_code == 409


def test_concurrent_request_idempotency(mobile):
    svc = MobilePaymentWorkflow(mobile.engine, mobile.settings, mobile.public)
    data = MobilePaymentInput(request_key='same-concurrent', destination=ADDRESS, amount_zatoshis=1)
    def run(_):
        return svc.prepare(data, Identity('owner', mobile.settings.dev_owner_id)).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(run, range(2)))
    assert ids[0] == ids[1]
    mobile.wallet.send.assert_not_called()
