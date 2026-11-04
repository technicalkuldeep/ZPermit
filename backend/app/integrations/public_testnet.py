"""Read-only TLS lightwallet client, independent of Zingo's private wallet IPC.

No SendTransaction method, keys, wallet files, or shielded balance inference.
The public server is a trusted observation source, not a locally validated node.
"""
import json
from pathlib import Path
import re
import subprocess

import grpc

from app.integrations.lightwallet_proto import service_pb2 as rpc
from app.integrations.lightwallet_proto import compact_formats_pb2 as compact
from app.integrations.zcash import NU7_BRANCH, NU7_HEIGHT, TXID, ZcashError

SERVER = 'testnet.zec.rocks:443'
SERVICE = '/cash.z.wallet.sdk.rpc.CompactTxStreamer/'


class PublicInspector:
    def __init__(self, settings):
        self.config = settings

    def inspect(self, payload):
        path = Path(self.config.zcash_public_inspector_binary)
        if not path.is_absolute() or not path.is_file():
            raise ZcashError('public_inspector_not_installed')
        try:
            r = subprocess.run([str(path)], input=json.dumps(payload).encode(),
                               capture_output=True, shell=False, check=False,
                               timeout=self.config.zcash_timeout_seconds, env={})
            if r.returncode or len(r.stdout) > 8192:
                raise ZcashError('public_data_invalid')
            result = json.loads(r.stdout)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except subprocess.TimeoutExpired:
            raise ZcashError('public_inspector_timeout') from None
        except (OSError, ValueError):
            raise ZcashError('public_inspector_unavailable') from None

    def address(self, address):
        if not isinstance(address, str) or not re.fullmatch(r'utest1[023456789acdefghjklmnpqrstuvwxyz]{20,1000}', address):
            raise ZcashError('testnet_unified_address_required')
        result = self.inspect({'kind': 'address', 'address': address})
        if (result.get('network') != 'test' or result.get('valid') is not True
                or result.get('orchard_receiver') is not True):
            raise ZcashError('testnet_unified_address_required')
        return {'address': address, **result, 'ownership_verified': False}


class PublicTestnetClient:
    """Only five named read RPCs are callable. Never opens a local wallet."""
    def __init__(self, settings, inspector=None):
        self.config = settings
        self.inspector = inspector or PublicInspector(settings)

    def read(self, method, request, response_type):
        if not self.config.zcash_public_reads_enabled:
            raise ZcashError('public_testnet_reads_disabled')
        if method not in {'GetLightdInfo', 'GetLatestBlock', 'GetTransaction', 'GetBlock', 'GetTreeState'}:
            raise ZcashError('unsupported_public_read')
        try:
            with grpc.secure_channel(SERVER, grpc.ssl_channel_credentials(), options=(
                    ('grpc.max_receive_message_length', 4_000_000),
                    ('grpc.enable_retries', 0), ('grpc.enable_http_proxy', 0))) as channel:
                call = channel.unary_unary(SERVICE + method,
                          request_serializer=type(request).SerializeToString,
                          response_deserializer=response_type.FromString)
                return call(request, timeout=self.config.zcash_timeout_seconds, wait_for_ready=False)
        except grpc.RpcError as exc:
            code = 'public_testnet_timeout' if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED else 'public_testnet_unavailable'
            raise ZcashError(code) from None
        except Exception:
            raise ZcashError('public_testnet_response_invalid') from None

    def readiness(self):
        info = self.read('GetLightdInfo', rpc.Empty(), rpc.LightdInfo)
        if info.chainName != 'test' or info.consensusBranchId.lower() != NU7_BRANCH or info.blockHeight < NU7_HEIGHT:
            raise ZcashError('nu7_testnet_required')
        tip = self.read('GetLatestBlock', rpc.ChainSpec(), rpc.BlockID)
        if tip.height < NU7_HEIGHT or abs(tip.height - info.blockHeight) > 6 or len(tip.hash) != 32:
            raise ZcashError('public_testnet_not_ready')
        tree = self.read('GetTreeState', rpc.BlockID(height=tip.height), rpc.TreeState)
        if tree.network != 'test' or tree.height != tip.height or not tree.ironwoodTree:
            raise ZcashError('ironwood_server_required')
        return {'network': 'test', 'nu7_branch': NU7_BRANCH, 'height': tip.height,
                'server': 'https://' + SERVER, 'ready': True,
                'wallet_connected': False, 'wallet_balance_supported': False,
                'signing_supported': False, 'trust': 'remote_lightwallet_server',
                'lightwallet_protocol_version': info.lightwalletProtocolVersion}

    def receiving_address(self):
        if not self.config.zcash_public_receiving_address:
            raise ZcashError('public_receiving_address_required')
        self.readiness()
        return self.inspector.address(self.config.zcash_public_receiving_address)

    def transaction(self, txid):
        if not isinstance(txid, str) or not TXID.fullmatch(txid):
            raise ZcashError('invalid_transaction_id')
        ready = self.readiness()
        raw = self.read('GetTransaction', rpc.TxFilter(hash=bytes.fromhex(txid)[::-1]), rpc.RawTransaction)
        if not raw.data or len(raw.data) > 2_000_000:
            raise ZcashError('public_transaction_unavailable')
        decoded = self.inspector.inspect({'kind': 'transaction', 'raw_hex': raw.data.hex()})
        if decoded.get('txid') != txid or decoded.get('nu7_branch') != NU7_BRANCH or decoded.get('pool') != 'ironwood':
            raise ZcashError('public_transaction_mismatch')
        if raw.height in {0, 0xffffffffffffffff}:
            return {**decoded, 'network': 'test', 'status': 'pending' if raw.height == 0 else 'off_chain',
                    'height': None, 'confirmations': 0, 'blockhash': None,
                    'verified_mined': False, 'trust': 'remote_lightwallet_server'}
        if raw.height < NU7_HEIGHT or raw.height > ready['height']:
            raise ZcashError('public_transaction_height_invalid')
        block = self.read('GetBlock', rpc.BlockID(height=raw.height), compact.CompactBlock)
        if (block.height != raw.height or len(block.hash) != 32
                or not any(tx.txid == bytes.fromhex(txid)[::-1] and tx.ironwoodActions for tx in block.vtx)):
            raise ZcashError('public_transaction_inclusion_unverified')
        tree = self.read('GetTreeState', rpc.BlockID(height=raw.height), rpc.TreeState)
        blockhash = block.hash[::-1].hex()
        if tree.network != 'test' or tree.height != raw.height or tree.hash.lower() != blockhash:
            raise ZcashError('public_transaction_inclusion_unverified')
        return {**decoded, 'network': 'test', 'status': 'mined', 'height': raw.height,
                'confirmations': ready['height'] - raw.height + 1, 'blockhash': blockhash,
                'verified_mined': True, 'trust': 'remote_lightwallet_server'}
