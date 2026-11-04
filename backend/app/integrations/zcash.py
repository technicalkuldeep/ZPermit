"""Documented Zallet subprocess boundary. No key import, unlocking, or shell.

Contract: upstream b0034a0925fc0c12eb4cd619114c3287b160093f.
No supported wallet is bundled; live compatibility must be checked by operator.
"""
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

import httpx

NU7_HEIGHT = 4_465_026
NU7_BRANCH = '77190ad9'
TXID = re.compile(r'^[0-9a-f]{64}$')
OPID = re.compile(r'^opid-[a-zA-Z0-9-]{1,100}$')


def rpc_json(value):
    """Encode exact coin amounts as JSON numbers, never binary floats."""
    if isinstance(value, Decimal):
        return format(value, '.8f')
    if isinstance(value, list):
        return '[' + ','.join(rpc_json(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + ':' + rpc_json(v) for k, v in value.items()) + '}'
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


class ZcashError(Exception):
    def __init__(self, code='wallet_unavailable'):
        self.code = code
        super().__init__(code)


def loopback_url(value):
    u = urlsplit(value)
    return (u.scheme == 'http' and u.hostname in {'127.0.0.1', '::1'}
            and u.port is not None and not u.username and not u.password
            and u.path in {'', '/'} and not u.query and not u.fragment)


class ZalletAdapter:
    def __init__(self, settings):
        self.config = settings

    def local_config(self):
        c = self.config
        if not c.zcash_enabled or not c.zcash_zallet_config or not c.zcash_zallet_datadir:
            raise ZcashError('wallet_not_configured')
        try:
            if not all(Path(p).is_absolute() for p in
                       (c.zcash_zallet_binary, c.zcash_zallet_config, c.zcash_zallet_datadir)):
                raise ValueError()
            data = tomllib.loads(Path(c.zcash_zallet_config).read_text())
            if data['consensus'] != {'network': 'test'}:
                raise ValueError()
            binds = data['rpc']['bind']
            if not binds or not all(loopback_url('http://' + b) for b in binds):
                raise ValueError()
            if data.get('rpc', {}).get('allow_insecure_remote_bind', False):
                raise ValueError()
            if not loopback_url(c.zcash_zebra_rpc_url):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise ZcashError('unsafe_wallet_configuration') from None
        return data

    def rpc(self, method, *params):
        self.local_config()
        c = self.config
        try:
            result = subprocess.run(
                [c.zcash_zallet_binary, '--config', c.zcash_zallet_config,
                 '--datadir', c.zcash_zallet_datadir, 'rpc', method,
                 *[rpc_json(p) for p in params]],
                shell=False, stdin=subprocess.DEVNULL, capture_output=True,
                timeout=c.zcash_timeout_seconds, check=False,
                # No API credentials or wallet secrets in inherited environment.
                env={'PATH': os.defpath, 'HOME': str(Path(c.zcash_zallet_datadir).parent)},
            )
            if result.returncode != 0:
                raise ZcashError('wallet_rpc_failed')
            if len(result.stdout) > 2_000_000:
                raise ZcashError('wallet_response_invalid')
            # Released rpc CLI prints string results unquoted (rpc_cli.rs).
            if method == 'z_sendmany':
                raw = result.stdout.decode('ascii').strip()
                if not OPID.fullmatch(raw):
                    raise ZcashError('wallet_response_invalid')
                return raw
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            raise ZcashError('wallet_timeout') from None
        except (OSError, ValueError):
            raise ZcashError('wallet_response_invalid') from None

    def node(self, method, *params):
        self.local_config()
        try:
            with httpx.Client(timeout=self.config.zcash_timeout_seconds, trust_env=False,
                              follow_redirects=False) as client:
                response = client.post(self.config.zcash_zebra_rpc_url,
                                       json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': list(params)})
            response.raise_for_status()
            data = response.json()
            if data.get('error') or 'result' not in data:
                raise ZcashError('node_rpc_failed')
            return data['result']
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise ZcashError('node_unavailable') from None

    def readiness(self):
        self.local_config()
        n = self.node('getblockchaininfo')
        w = self.rpc('getwalletstatus')
        try:
            height = n['blocks']
            if (n['chain'] != 'test' or type(height) is not int or height < NU7_HEIGHT
                    or n['consensus']['chaintip'].lower() != NU7_BRANCH
                    or n['consensus']['nextblock'].lower() != NU7_BRANCH):
                raise ZcashError('nu7_testnet_required')
            if (n.get('verificationprogress', 0) < 0.999 or w['locked'] is not False
                    or w['node_tip']['height'] != height
                    or w['node_tip']['blockhash'] != n['bestblockhash']
                    or w['wallet_tip'] != w['node_tip']
                    or w['fully_synced_height'] != height or w.get('sync_work_remaining')):
                raise ZcashError('wallet_not_synced')
        except (KeyError, TypeError, AttributeError):
            raise ZcashError('wallet_response_invalid') from None
        if not self.config.zcash_account_id or not self.config.zcash_source_address:
            raise ZcashError('wallet_account_not_configured')
        account = self.rpc('z_getaccount', self.config.zcash_account_id)
        try:
            if (account['account_uuid'] != self.config.zcash_account_id
                    or not isinstance(account['addresses'], list)
                    or not any(a.get('ua') == self.config.zcash_source_address
                               for a in account['addresses'])):
                raise ZcashError('wallet_source_account_mismatch')
        except (KeyError, TypeError, AttributeError):
            raise ZcashError('wallet_response_invalid') from None
        self.address(self.config.zcash_source_address)
        return {'network': 'test', 'nu7_branch': NU7_BRANCH, 'height': height, 'ready': True}

    def address(self, address):
        if not re.fullmatch(r'utest1[023456789acdefghjklmnpqrstuvwxyz]{20,1000}', address):
            raise ZcashError('testnet_unified_address_required')
        receivers = self.rpc('z_listunifiedreceivers', address)
        if not isinstance(receivers, dict) or not isinstance(receivers.get('orchard'), str):
            raise ZcashError('orchard_receiver_required')
        orchard = receivers['orchard']
        if not re.fullmatch(r'utest1[023456789acdefghjklmnpqrstuvwxyz]{20,1000}', orchard):
            raise ZcashError('wallet_response_invalid')
        # Use only the Orchard receiver: no transparent or Sapling fallback.
        return orchard

    def balance(self):
        self.readiness()
        result = self.rpc('z_getbalanceforaccount', self.config.zcash_account_id, 10)
        try:
            pools = result['pools']
            if result['minimum_confirmations'] != 10 or not isinstance(pools, dict):
                raise ValueError()
            balances = {pool: pools.get(pool, {}).get('valueZat', 0)
                        for pool in ('sapling', 'orchard', 'ironwood')}
            if any(type(v) is not int or v < 0 for v in balances.values()):
                raise ValueError()
            return {'network': 'test', 'minimum_confirmations': 10, 'shielded_zatoshis': balances}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ZcashError('wallet_response_invalid') from None

    def send(self, source, destination, amount_zatoshis):
        amount = Decimal(amount_zatoshis) / Decimal(100_000_000)
        opid = self.rpc('z_sendmany', source, [{'address': destination, 'amount': amount}],
                        10, None, 'FullPrivacy')
        if not isinstance(opid, str) or not OPID.fullmatch(opid):
            raise ZcashError('wallet_response_invalid')
        return opid

    def operation(self, opid):
        result = self.rpc('z_getoperationstatus', [opid])
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise ZcashError('operation_lost')
        op = result[0]
        if op.get('id') != opid or op.get('status') not in {'queued', 'executing', 'success', 'failed', 'cancelled'}:
            raise ZcashError('wallet_response_invalid')
        return op

    def transaction(self, txid):
        if not TXID.fullmatch(txid):
            raise ZcashError('wallet_response_invalid')
        r = self.rpc('z_viewtransaction', txid)
        try:
            confirmations = r['confirmations']
            if (r['txid'] != txid or type(confirmations) is not int or confirmations < -1
                    or r['status'] not in {'mined', 'waiting', 'expiringsoon', 'expired'}):
                raise ValueError()
            return {'txid': txid, 'confirmations': confirmations, 'status': r['status'],
                    'blockhash': r.get('blockhash')}
        except (KeyError, TypeError, ValueError):
            raise ZcashError('wallet_response_invalid') from None

    def evidence(self, txid):
        """Read-only full-node evidence, not a Python proof verifier.

        Zebra 7 TransactionObject serializes vin/vout, vShieldedSpend,
        vShieldedOutput, vjoinsplit and separate orchard/ironwood objects.
        Fail closed unless a mined pure Ironwood v6 transaction is observed.
        """
        self.readiness()
        if not isinstance(txid, str) or not TXID.fullmatch(txid):
            raise ZcashError('transaction_id_unavailable')
        r = self.node('getrawtransaction', txid, 1)
        try:
            height, confirmations = r['height'], r['confirmations']
            if (r['txid'] != txid or r['version'] != 6
                    or type(height) is not int or height < NU7_HEIGHT
                    or type(confirmations) is not int or confirmations < 1
                    or any(r[k] != [] for k in
                           ('vin', 'vout', 'vShieldedSpend', 'vShieldedOutput', 'vjoinsplit'))
                    or r['orchard']['actions'] != []):
                raise ValueError()
            actions = r['ironwood']['actions']
            if not isinstance(actions, list) or not actions:
                raise ValueError()
            blockhash = r['blockhash']
            if not isinstance(blockhash, str) or not TXID.fullmatch(blockhash):
                raise ValueError()
            if self.node('getblockhash', height) != blockhash:
                raise ZcashError('transaction_not_in_best_chain')
            return {'txid': txid, 'network': 'test', 'nu7_branch': NU7_BRANCH,
                    'pool': 'ironwood', 'height': height, 'blockhash': blockhash,
                    'confirmations': confirmations, 'shielded_actions': len(actions),
                    'transparent_inputs': 0, 'transparent_outputs': 0,
                    'verification': 'trusted_local_zebra_best_chain'}
        except (KeyError, TypeError, ValueError):
            raise ZcashError('shielded_mined_evidence_unavailable') from None
