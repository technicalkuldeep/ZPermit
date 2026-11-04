"""TEST DOUBLES ONLY. Synthetic addresses and hashes are not live evidence."""
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import grpc
import pytest
from sqlalchemy.orm import Session

from test_spending import world
from app.core.config import Settings
from app.integrations.public_testnet import PublicInspector, PublicTestnetClient
from app.integrations.lightwallet_proto import service_pb2 as rpc, compact_formats_pb2 as compact
from app.integrations.zcash import NU7_HEIGHT, ZcashError
from app.models.public_testnet import PublicTransactionObservation

TXID = '12'*32  # Synthetic fixture, never public-testnet evidence.
ADDRESS = 'utest1'+'q'*80  # Deliberately checksum-invalid.
BASE = '/api/zcash/public'


@pytest.fixture(autouse=True)
def block_live(monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('Real subprocess/network forbidden in unit tests')
    monkeypatch.setattr(grpc,'secure_channel',forbidden)
    monkeypatch.setattr(subprocess,'run',forbidden)


@pytest.fixture
def client():
    c = PublicTestnetClient(Settings(_env_file=None,zcash_public_reads_enabled=True))
    c.inspector = Mock()
    c.inspector.inspect.return_value = dict(txid=TXID,nu7_branch='77190ad9',pool='ironwood',version=6,
        ironwood_actions=2,transparent_inputs=0,transparent_outputs=0,single_shielded_pool=True)
    c.responses = {
        'GetLightdInfo':rpc.LightdInfo(chainName='test',consensusBranchId='77190ad9',blockHeight=NU7_HEIGHT+50),
        'GetLatestBlock':rpc.BlockID(height=NU7_HEIGHT+50,hash=b'\xab'*32),
        'GetTransaction':rpc.RawTransaction(data=b'SYNTHETIC DATA',height=NU7_HEIGHT+49),
        'GetBlock':compact.CompactBlock(height=NU7_HEIGHT+49,hash=b'\xab'*32,vtx=[
            compact.CompactTx(index=1,txid=bytes.fromhex(TXID)[::-1],ironwoodActions=[
                compact.CompactOrchardAction(nullifier=b'\x33'*32)])]),
    }
    def read(method,request,response_type):
        if method=='GetTreeState': return rpc.TreeState(network='test',height=request.height,hash='ab'*32,ironwoodTree='test-double-tree')
        return c.responses[method]
    c.read = Mock(side_effect=read)
    return c


def test_server_readiness_is_not_wallet_readiness(client):
    r=client.readiness()
    assert r['ready'] and not r['wallet_connected'] and not r['signing_supported']
    assert not r['wallet_balance_supported'] and not hasattr(client,'balance') and not hasattr(client,'send')


@pytest.mark.parametrize('chain,branch,height',[('main','77190ad9',NU7_HEIGHT+1),('regtest','77190ad9',NU7_HEIGHT+1),('test','00000000',NU7_HEIGHT+1),('test','77190ad9',1)])
def test_network_mismatch(client,chain,branch,height):
    client.responses['GetLightdInfo']=rpc.LightdInfo(chainName=chain,consensusBranchId=branch,blockHeight=height)
    with pytest.raises(ZcashError,match='nu7_testnet_required'): client.readiness()


def test_transaction_confirmation_and_txid_order(client):
    r=client.transaction(TXID)
    assert r['verified_mined'] and r['confirmations']==2 and r['trust']=='remote_lightwallet_server'
    call=next(x for x in client.read.call_args_list if x.args[0]=='GetTransaction')
    assert call.args[1].hash==bytes.fromhex(TXID)[::-1]


@pytest.mark.parametrize('height,status',[(0,'pending'),(2**64-1,'off_chain')])
def test_pending_and_fork(client,height,status):
    client.responses['GetTransaction'].height=height
    r=client.transaction(TXID)
    assert r['status']==status and not r['verified_mined'] and r['confirmations']==0


def test_no_mined_claim_without_inclusion(client):
    client.responses['GetBlock'].vtx.clear()
    with pytest.raises(ZcashError,match='public_transaction_inclusion_unverified'): client.transaction(TXID)


def test_decoded_txid_must_match(client):
    client.inspector.inspect.return_value['txid']='34'*32
    with pytest.raises(ZcashError,match='public_transaction_mismatch'): client.transaction(TXID)


@pytest.mark.parametrize('txid',['fake','12'*31,'AB'*32])
def test_invalid_txid_no_rpc(client,txid):
    with pytest.raises(ZcashError,match='invalid_transaction_id'): client.transaction(txid)
    client.read.assert_not_called()


def test_no_public_send_and_disabled_default():
    c=PublicTestnetClient(Settings(_env_file=None))
    with pytest.raises(ZcashError,match='public_testnet_reads_disabled'): c.readiness()
    c.config.zcash_public_reads_enabled=True
    with pytest.raises(ZcashError,match='unsupported_public_read'): c.read('SendTransaction',rpc.Empty(),rpc.Empty)


@pytest.fixture
def inspector(tmp_path):
    p=tmp_path/'decoder';p.touch()
    return PublicInspector(Settings(_env_file=None,zcash_public_inspector_binary=str(p)))


@pytest.mark.parametrize('address',['u1abc','tm123','ztestsapling123','utest1bad','phrase '*24])
def test_invalid_addresses(inspector,address):
    with pytest.raises(ZcashError,match='testnet_unified_address_required'): inspector.address(address)


def test_missing_decoder():
    c=PublicInspector(Settings(_env_file=None,zcash_public_inspector_binary='/not/installed'))
    with pytest.raises(ZcashError,match='public_inspector_not_installed'): c.address(ADDRESS)


def test_decoder_stdin_and_no_secrets(inspector,monkeypatch):
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout=b'{"network":"test","valid":true,"orchard_receiver":true}'))
    monkeypatch.setattr(subprocess,'run',run)
    assert not inspector.address(ADDRESS)['ownership_verified']
    args,kw=run.call_args
    assert len(args[0])==1 and kw['shell'] is False and kw['env']=={} and b'utest1' in kw['input']


@pytest.mark.parametrize('error,code',[(subprocess.TimeoutExpired('private',1),'public_inspector_timeout'),(OSError('private'),'public_inspector_unavailable')])
def test_decoder_errors_sanitized(inspector,monkeypatch,error,code):
    monkeypatch.setattr(subprocess,'run',Mock(side_effect=error))
    with pytest.raises(ZcashError,match=code): inspector.address(ADDRESS)


def test_bad_checksum_rejected(inspector,monkeypatch):
    monkeypatch.setattr(subprocess,'run',Mock(return_value=SimpleNamespace(returncode=1,stdout=b'private')))
    with pytest.raises(ZcashError,match='public_data_invalid'): inspector.address(ADDRESS)


@pytest.mark.parametrize('status,code',[(grpc.StatusCode.DEADLINE_EXCEEDED,'public_testnet_timeout'),(grpc.StatusCode.UNAVAILABLE,'public_testnet_unavailable')])
def test_server_unavailable_timeout(monkeypatch,status,code):
    error=grpc.RpcError();error.code=lambda:status
    context=MagicMock();context.__enter__.return_value.unary_unary.return_value.side_effect=error
    monkeypatch.setattr(grpc,'secure_channel',Mock(return_value=context))
    c=PublicTestnetClient(Settings(_env_file=None,zcash_public_reads_enabled=True))
    with pytest.raises(ZcashError,match=code):c.readiness()


@pytest.fixture
def observed(world,client):
    world.client.app.state.public_testnet=client;world.public=client
    return world


def record(w,**changes):
    return w.client.post(BASE+'/transactions',headers=w.owner,json=dict(txid=TXID,request_key='gui-test-1',**changes))


def test_persist_idempotency_and_policy_isolation(observed):
    w=observed;permit=w.permit();w.submit(permit);before=w.summary(permit)
    p=record(w).json()
    assert p['origin']=='wallet_initiated_owner_report' and p['evidence']['verified_mined']
    assert record(w).json()['id']==p['id']
    assert w.client.post(BASE+'/transactions',headers=w.owner,json={'txid':'34'*32,'request_key':'gui-test-1'}).status_code==409
    assert w.client.post(BASE+'/transactions',headers=w.owner,json={'txid':TXID,'request_key':'other-key'}).status_code==409
    with Session(w.engine) as s:assert s.get(PublicTransactionObservation,p['id']).txid==TXID
    assert w.summary(permit)==before


def test_failed_lookup_does_not_persist(observed):
    w=observed;w.public.transaction=Mock(side_effect=ZcashError('public_testnet_unavailable'))
    assert record(w).status_code==503
    with Session(w.engine) as s:assert s.query(PublicTransactionObservation).count()==0


def test_failed_refresh_stale_evidence(observed):
    w=observed;p=record(w).json();w.public.transaction=Mock(side_effect=ZcashError('public_testnet_timeout'))
    r=w.client.post(f"{BASE}/transactions/{p['id']}/refresh",headers=w.owner).json()
    assert not r['last_check_succeeded'] and r['error_code']=='public_testnet_timeout'
    assert r['last_verified_at']==p['last_verified_at'] and r['evidence']==p['evidence']


def test_reorg_updates_confirmations(observed):
    w=observed;p=record(w).json();w.public.responses['GetTransaction'].height=0
    r=w.client.post(f"{BASE}/transactions/{p['id']}/refresh",headers=w.owner).json()
    assert r['evidence']['status']=='pending' and r['evidence']['confirmations']==0


def test_owner_only(observed):
    w=observed;p=record(w).json()
    for method,path,payload in [('GET','/readiness',None),('GET','/receiving-address',None),('POST','/validate-address',{'address':ADDRESS}),('POST','/transactions',{'txid':TXID,'request_key':'x'}),('GET',f"/transactions/{p['id']}",None),('POST',f"/transactions/{p['id']}/refresh",None)]:
        for headers,code in [(w.agent,403),({},401)]:
            assert w.client.request(method,BASE+path,json=payload,headers=headers).status_code==code


@pytest.mark.parametrize('field',['seed_phrase','private_key','purchase_request_id','origin'])
def test_no_wallet_secret_or_spending_authority_inputs(observed,field):
    assert record(observed,**{field:'forbidden'}).status_code==422


def test_observation_owner_visibility(observed):
    w=observed;p=record(w).json()
    with Session(w.engine) as s:
        s.get(PublicTransactionObservation,p['id']).owner_id='different-owner'
        s.commit()
    assert w.client.get(f"{BASE}/transactions/{p['id']}",headers=w.owner).status_code==404
    assert w.client.post(f"{BASE}/transactions/{p['id']}/refresh",headers=w.owner).status_code==404


def test_missing_receiving_address_is_not_generated(client):
    with pytest.raises(ZcashError,match='public_receiving_address_required'):
        client.receiving_address()
    client.read.assert_not_called()
