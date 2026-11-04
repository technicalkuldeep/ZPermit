"""TEST DOUBLES ONLY. Synthetic IDs/addresses below are not testnet evidence.
No wallet process or network transport may run in this unit suite.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from test_spending import world
from app.core.config import Settings
from app.core.security import Identity
from app.integrations.zcash import NU7_HEIGHT, ZalletAdapter, ZcashError, rpc_json
from app.models.spending import utcnow
from app.models.zcash import TestnetPayment as PaymentRecord
from app.schemas.zcash import PaymentConfirmation
from app.services.zcash import ZcashWorkflow

# Deliberately synthetic, checksum-invalid fixtures; only a mocked wallet accepts them.
ADDRESS = 'utest1' + 'q' * 80
DESTINATION = 'utest1' + 'p' * 80
SYNTHETIC_TXID = 'ab' * 32
OPID = 'opid-11111111-1111-1111-1111-111111111111'
ACK = 'SEND TESTNET TAZ WITH AUTOMATIC ZIP317 FEE'
BASE = '/api/zcash/payment-requests'


@pytest.fixture(autouse=True)
def no_live_wallet(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Real wallet/network is forbidden in Zcash unit tests')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', forbidden)


class WalletDouble:
    """Domain double, not an assertion of a live wallet or real address validity."""
    def __init__(self):
        self.send_calls = 0
        self.send_error = None
        self.lookup_error = None
        self.operation_data = {'id': OPID, 'status': 'success',
                               'result': {'txids': [SYNTHETIC_TXID], 'broadcast': True}}

    def readiness(self):
        return {'ready': True, 'network': 'test'}

    def address(self, value):
        return value

    def send(self, *args):
        self.send_calls += 1
        if self.send_error:
            raise self.send_error
        return OPID

    def operation(self, opid):
        if isinstance(self.operation_data, Exception):
            raise self.operation_data
        return self.operation_data

    def transaction(self, txid):
        if self.lookup_error:
            raise self.lookup_error
        return {'txid': txid, 'confirmations': 2, 'status': 'mined'}


@pytest.fixture
def zworld(world):
    world.settings.zcash_source_address = ADDRESS
    world.settings.zcash_account_id = 'test-account'
    wallet = WalletDouble()
    world.client.app.state.zcash_wallet = wallet
    world.wallet = wallet
    return world


def prepare(w, **changes):
    data = {'destination': DESTINATION, 'amount_zatoshis': 100000, 'request_key': 'test-1'}
    data.update(changes)
    return w.client.post(BASE, json=data, headers=w.owner)


def confirm(w, p, **changes):
    data = {'fingerprint': p['fingerprint'], 'confirmation': ACK}
    data.update(changes)
    return w.client.post(f"{BASE}/{p['id']}/confirm", json=data, headers=w.owner)


def refresh(w, p):
    return w.client.post(f"{BASE}/{p['id']}/refresh", headers=w.owner)


def test_prepare_persist_idempotent_and_no_send(zworld):
    w = zworld
    p = prepare(w).json()
    assert p['state'] == 'pending_approval' and p['txid'] is None
    assert prepare(w).json()['id'] == p['id']
    assert prepare(w, amount_zatoshis=1).status_code == 409
    assert w.client.get(f"{BASE}/{p['id']}", headers=w.owner).json() == p
    assert w.wallet.send_calls == 0


@pytest.mark.parametrize('amount', [0, -1, True, 1.0, '1', 100000001])
def test_strict_amount(zworld, amount):
    assert prepare(zworld, amount_zatoshis=amount).status_code == 422


@pytest.mark.parametrize('field', ['seed_phrase', 'spending_key', 'owner_id', 'state', 'txid', 'purchase_request_id'])
def test_forbid_extra_fields(zworld, field):
    assert prepare(zworld, **{field: 'forbidden'}).status_code == 422
    assert zworld.wallet.send_calls == 0


def test_owner_only_all_routes(zworld):
    w = zworld
    p = prepare(w).json()
    calls = [('get', '/api/zcash/readiness', None), ('get', '/api/zcash/balance', None),
             ('post', BASE, {'destination': DESTINATION, 'amount_zatoshis': 1, 'request_key': 'x'}),
             ('get', f"{BASE}/{p['id']}", None), ('get', f"{BASE}/{p['id']}/evidence", None), ('post', f"{BASE}/{p['id']}/refresh", None),
             ('post', f"{BASE}/{p['id']}/confirm", {'fingerprint': p['fingerprint'], 'confirmation': ACK})]
    for method, url, payload in calls:
        assert w.client.request(method, url, json=payload, headers=w.agent).status_code == 403
        assert w.client.request(method, url, json=payload).status_code == 401
    assert w.wallet.send_calls == 0


def test_disabled_and_exact_confirmation(zworld):
    w = zworld
    p = prepare(w).json()
    assert confirm(w, p).status_code == 409
    w.settings.zcash_live_broadcast_enabled = True
    assert confirm(w, p, fingerprint='f' * 64).status_code == 409
    assert confirm(w, p, confirmation='yes').status_code == 422
    assert w.wallet.send_calls == 0


def test_confirm_refresh_persistence_no_usd_settlement(zworld):
    w = zworld
    permit = w.permit()
    purchase = w.submit(permit)
    before = w.summary(permit)
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    assert confirm(w, p).json()['state'] == 'submitted'
    assert confirm(w, p).json()['operation_id'] == OPID
    r = refresh(w, p).json()
    assert r['state'] == 'broadcast' and r['txid'] == SYNTHETIC_TXID
    assert r['confirmations'] == 2
    assert w.wallet.send_calls == 1
    assert w.summary(permit) == before
    assert w.client.get(f"/api/purchase-requests/{purchase['id']}", headers=w.owner).json()['state'] == 'authorized'
    with Session(w.engine) as s:
        assert s.get(PaymentRecord, p['id']).txid == SYNTHETIC_TXID


@pytest.mark.parametrize('error', [ZcashError('wallet_timeout'), RuntimeError('secret provider output')])
def test_unknown_send_never_retries(zworld, error):
    w = zworld
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    w.wallet.send_error = error
    r = confirm(w, p)
    assert r.json()['state'] == 'uncertain'
    assert 'secret' not in r.text
    assert confirm(w, p).json()['state'] == 'uncertain'
    assert w.wallet.send_calls == 1


def test_crash_claim_never_rebroadcast(zworld):
    w = zworld
    p = prepare(w).json()
    with Session(w.engine) as s:
        s.get(PaymentRecord, p['id']).state = 'initiating'
        s.commit()
    w.settings.zcash_live_broadcast_enabled = True
    assert confirm(w, p).json()['state'] == 'initiating'
    assert refresh(w, p).json()['state'] == 'uncertain'
    assert w.wallet.send_calls == 0


@pytest.mark.parametrize('change', ['expiry', 'source', 'account', 'datadir'])
def test_confirmation_rechecks(zworld, change):
    w = zworld
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    if change == 'expiry':
        with Session(w.engine) as s:
            s.get(PaymentRecord, p['id']).expires_at = utcnow() - timedelta(seconds=1)
            s.commit()
    else:
        setattr(w.settings, {'source': 'zcash_source_address', 'account': 'zcash_account_id',
                            'datadir': 'zcash_zallet_datadir'}[change], 'changed')
    assert confirm(w, p).status_code == 409
    assert w.wallet.send_calls == 0


@pytest.mark.parametrize('result,state', [
    ({'id': OPID, 'status': 'executing'}, 'submitted'),
    ({'id': OPID, 'status': 'failed', 'error': {'message': 'secret'}}, 'failed'),
    ({'id': OPID, 'status': 'success', 'result': {'txids': [SYNTHETIC_TXID], 'broadcast': False}}, 'not_broadcast'),
    ({'id': OPID, 'status': 'success', 'result': {'txids': [SYNTHETIC_TXID]}}, 'uncertain'),
    ({'id': OPID, 'status': 'success', 'result': {'txids': ['fake'], 'broadcast': True}}, 'uncertain'),
    (ZcashError('operation_lost'), 'uncertain'),
])
def test_operation_results(zworld, result, state):
    w = zworld
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    confirm(w, p)
    w.wallet.operation_data = result
    r = refresh(w, p)
    assert r.json()['state'] == state
    assert 'secret' not in r.text
    confirm(w, p)
    assert w.wallet.send_calls == 1


def test_txid_survives_failed_followup_lookup(zworld):
    w = zworld
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    confirm(w, p)
    w.wallet.lookup_error = ZcashError('wallet_timeout')
    r = refresh(w, p).json()
    assert r['txid'] == SYNTHETIC_TXID and r['error_code'] == 'transaction_lookup_unavailable'


def test_competing_confirmations_single_send(zworld):
    w = zworld
    p = prepare(w).json()
    w.settings.zcash_live_broadcast_enabled = True
    def run(_):
        svc = ZcashWorkflow(w.engine, w.settings, w.wallet)
        return svc.confirm(p['id'], PaymentConfirmation(fingerprint=p['fingerprint'], confirmation=ACK),
                           Identity('owner', w.settings.dev_owner_id))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, range(2)))
    assert w.wallet.send_calls == 1


@pytest.fixture
def adapter(tmp_path):
    path = tmp_path / 'zallet.toml'
    path.write_text('[consensus]\nnetwork="test"\n[rpc]\nbind=["127.0.0.1:28232"]\n')
    c = Settings(_env_file=None, zcash_enabled=True, zcash_zallet_config=str(path),
                 zcash_zallet_datadir=str(tmp_path), zcash_account_id='test-account', zcash_source_address=ADDRESS)
    return ZalletAdapter(c)


def node_status():
    return {'chain': 'test', 'blocks': NU7_HEIGHT + 20, 'bestblockhash': 'cd' * 32,
            'consensus': {'chaintip': '77190ad9', 'nextblock': '77190ad9'}, 'verificationprogress': 1.0}


def wallet_status():
    return {'node_tip': {'height': NU7_HEIGHT + 20, 'blockhash': 'cd' * 32},
            'wallet_tip': {'height': NU7_HEIGHT + 20, 'blockhash': 'cd' * 32},
            'fully_synced_height': NU7_HEIGHT + 20, 'locked': False}


def test_adapter_readiness_contract(adapter):
    adapter.node = Mock(return_value=node_status())
    adapter.rpc = Mock(side_effect=[wallet_status(),
                       {'account_uuid': 'test-account', 'addresses': [{'ua': ADDRESS}]},
                       {'orchard': ADDRESS}])
    assert adapter.readiness()['ready'] is True


@pytest.mark.parametrize('field,value', [('chain', 'main'), ('blocks', 10),
                                         ('consensus', {'chaintip': 'bad', 'nextblock': 'bad'})])
def test_wrong_network_or_upgrade(adapter, field, value):
    n = node_status(); n[field] = value
    adapter.node = Mock(return_value=n)
    adapter.rpc = Mock(return_value=wallet_status())
    with pytest.raises(ZcashError): adapter.readiness()


@pytest.mark.parametrize('field,value', [('locked', True), ('wallet_tip', None),
                                         ('fully_synced_height', 1), ('sync_work_remaining', {'unscanned_blocks': 1})])
def test_unsynced_wallet(adapter, field, value):
    w = wallet_status(); w[field] = value
    adapter.node = Mock(return_value=node_status())
    adapter.rpc = Mock(return_value=w)
    with pytest.raises(ZcashError): adapter.readiness()


@pytest.mark.parametrize('address', ['u1abc', 'tm123', 'ztestsapling123', 'tex1abc', 'utest1bad', 'word ' * 24])
def test_invalid_addresses_do_not_reach_wallet(adapter, address):
    adapter.rpc = Mock()
    with pytest.raises(ZcashError): adapter.address(address)
    adapter.rpc.assert_not_called()


def test_decode_and_select_orchard_receiver(adapter):
    adapter.rpc = Mock(return_value={'orchard': DESTINATION, 'p2pkh': 'ignored'})
    assert adapter.address(ADDRESS) == DESTINATION
    adapter.rpc.assert_called_once_with('z_listunifiedreceivers', ADDRESS)
    adapter.rpc.return_value = {'sapling': 'unsupported'}
    with pytest.raises(ZcashError): adapter.address(ADDRESS)


def test_balance_pool_and_units(adapter):
    adapter.readiness = Mock()
    adapter.rpc = Mock(return_value={'pools': {'ironwood': {'valueZat': 123}}, 'minimum_confirmations': 10})
    assert adapter.balance()['shielded_zatoshis'] == {'sapling': 0, 'orchard': 0, 'ironwood': 123}
    adapter.rpc.return_value = {'pools': {'orchard': {'valueZat': '123'}}, 'minimum_confirmations': 10}
    with pytest.raises(ZcashError): adapter.balance()


def test_send_contract_exact_json_amount(adapter):
    adapter.rpc = Mock(return_value=OPID)
    adapter.send(ADDRESS, DESTINATION, 100001)
    args = adapter.rpc.call_args.args
    assert args[0] == 'z_sendmany' and args[-3:] == (10, None, 'FullPrivacy')
    encoded = rpc_json(args[2])
    assert '0.00100001' in encoded
    assert json.loads(encoded, parse_float=Decimal)[0]['amount'] == Decimal('0.00100001')


@pytest.mark.parametrize('bad', ['main', 'regtest', 'custom'])
def test_settings_reject_non_testnet(bad):
    with pytest.raises(ValidationError): Settings(_env_file=None, zcash_network=bad)


@pytest.mark.parametrize('text', ['[consensus]\nnetwork="main"\n[rpc]\nbind=["127.0.0.1:28232"]',
                                 '[consensus]\nnetwork="test"\n[rpc]\nbind=["0.0.0.0:28232"]',
                                 'broken toml'])
def test_unsafe_local_config(adapter, text):
    Path(adapter.config.zcash_zallet_config).write_text(text)
    with pytest.raises(ZcashError): adapter.local_config()


def test_rpc_argv_no_shell_or_secrets(adapter, monkeypatch):
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"ok":true}', stderr=b''))
    monkeypatch.setattr(subprocess, 'run', runner)
    assert adapter.rpc('getwalletstatus') == {'ok': True}
    args, kw = runner.call_args
    assert args[0][1:3] == ['--config', adapter.config.zcash_zallet_config]
    assert kw['shell'] is False and kw['stdin'] == subprocess.DEVNULL
    assert 'ZPERMIT_DEV_OWNER_CREDENTIAL' not in kw['env']
    runner.return_value = SimpleNamespace(returncode=1, stdout=b'secret', stderr=b'secret')
    with pytest.raises(ZcashError, match='wallet_rpc_failed') as error: adapter.rpc('getwalletstatus')
    assert 'secret' not in str(error.value)


def test_rpc_timeout_sanitized(adapter, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', Mock(side_effect=subprocess.TimeoutExpired('secret', 1)))
    with pytest.raises(ZcashError, match='wallet_timeout'): adapter.rpc('getwalletstatus')


def test_unconfigured_api_returns_safe_error(world):
    r = world.client.get('/api/zcash/readiness', headers=world.owner)
    assert r.status_code == 503 and r.json()['detail']['code'] == 'wallet_not_configured'


def test_released_cli_returns_unquoted_operation_id(adapter, monkeypatch):
    runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=OPID.encode(), stderr=b''))
    monkeypatch.setattr(subprocess, 'run', runner)
    assert adapter.send(ADDRESS, DESTINATION, 1) == OPID
    argv = runner.call_args.args[0]
    assert '0.00000001' in argv[-4]
    assert argv[-3:] == ['10', 'null', '"FullPrivacy"']


def test_operation_poll_is_non_consuming(adapter):
    adapter.rpc = Mock(return_value=[{'id': OPID, 'status': 'executing'}])
    assert adapter.operation(OPID)['status'] == 'executing'
    adapter.rpc.assert_called_once_with('z_getoperationstatus', [OPID])
    adapter.rpc.return_value = []
    with pytest.raises(ZcashError, match='operation_lost'): adapter.operation(OPID)


def test_owner_cannot_see_other_owner_payment(zworld):
    w = zworld
    p = prepare(w).json()
    with Session(w.engine) as s:
        s.get(PaymentRecord, p['id']).owner_id = 'someone-else'
        s.commit()
    assert w.client.get(f"{BASE}/{p['id']}", headers=w.owner).status_code == 404
    assert refresh(w, p).status_code == 404


def test_node_loopback_transport_contract(adapter, monkeypatch):
    # MockTransport is a TEST DOUBLE, not a public node connection.
    def handler(request):
        assert request.url.host == '127.0.0.1'
        assert json.loads(request.content)['method'] == 'getblockchaininfo'
        return httpx.Response(200, json={'id': 1, 'result': node_status(), 'error': None})
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    assert adapter.node('getblockchaininfo')['chain'] == 'test'


def test_transaction_confirmations_allow_reorg(adapter):
    adapter.rpc = Mock(return_value={'txid': SYNTHETIC_TXID, 'confirmations': 0, 'status': 'waiting'})
    assert adapter.transaction(SYNTHETIC_TXID)['confirmations'] == 0
    adapter.rpc.return_value['confirmations'] = -1
    adapter.rpc.return_value['status'] = 'expired'
    assert adapter.transaction(SYNTHETIC_TXID)['status'] == 'expired'


def synthetic_node_transaction():
    # Fabricated response shape based on released Zebra source; never real evidence.
    return {'txid': SYNTHETIC_TXID, 'version': 6, 'height': NU7_HEIGHT + 1,
            'confirmations': 2, 'blockhash': 'cd' * 32, 'vin': [], 'vout': [],
            'vShieldedSpend': [], 'vShieldedOutput': [], 'vjoinsplit': [],
            'orchard': {'actions': []}, 'ironwood': {'actions': [{'synthetic': True}]}}


def test_node_evidence_is_mined_ironwood_only(adapter):
    adapter.readiness = Mock()
    adapter.node = Mock(side_effect=[synthetic_node_transaction(), 'cd' * 32])
    evidence = adapter.evidence(SYNTHETIC_TXID)
    assert evidence['pool'] == 'ironwood' and evidence['confirmations'] == 2
    assert evidence['verification'] == 'trusted_local_zebra_best_chain'
    assert adapter.node.call_args_list[0].args == ('getrawtransaction', SYNTHETIC_TXID, 1)
    assert adapter.node.call_args_list[1].args == ('getblockhash', NU7_HEIGHT + 1)


@pytest.mark.parametrize('change', [{'vin': [{}]}, {'vout': [{}]}, {'version': 5},
                                    {'confirmations': 0}, {'height': NU7_HEIGHT - 1},
                                    {'ironwood': {'actions': []}}, {'orchard': {'actions': [{}]}}])
def test_evidence_rejects_wrong_shape_or_unmined(adapter, change):
    r = synthetic_node_transaction(); r.update(change)
    adapter.readiness = Mock()
    adapter.node = Mock(return_value=r)
    with pytest.raises(ZcashError, match='shielded_mined_evidence_unavailable'):
        adapter.evidence(SYNTHETIC_TXID)


def test_evidence_rejects_noncanonical_block(adapter):
    adapter.readiness = Mock()
    adapter.node = Mock(side_effect=[synthetic_node_transaction(), 'ef' * 32])
    with pytest.raises(ZcashError, match='transaction_not_in_best_chain'):
        adapter.evidence(SYNTHETIC_TXID)


@pytest.mark.parametrize('account', [
    {'account_uuid': 'other-account', 'addresses': [{'ua': ADDRESS}]},
    {'account_uuid': 'test-account', 'addresses': [{'ua': DESTINATION}]},
])
def test_readiness_requires_source_in_configured_account(adapter, account):
    adapter.node = Mock(return_value=node_status())
    adapter.rpc = Mock(side_effect=[wallet_status(), account])
    with pytest.raises(ZcashError, match='wallet_source_account_mismatch'):
        adapter.readiness()
