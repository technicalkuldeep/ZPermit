"""EXPLICITLY OPT-IN REAL READS ONLY. This file never invokes a send method.

ZPERMIT_RUN_LIVE_TESTNET_READS=1 .venv/bin/python -m pytest -q tests/test_zcash_live.py
A configured synced wallet with confirmed shielded testnet funds is required.
"""
import os

import pytest

from app.core.config import Settings
from app.integrations.zcash import ZalletAdapter


@pytest.mark.skipif(os.environ.get('ZPERMIT_RUN_LIVE_TESTNET_READS') != '1',
                    reason='Opt-in live testnet reads require a configured funded wallet')
def test_live_wallet_readiness_and_funded_shielded_balance():
    wallet = ZalletAdapter(Settings())
    status = wallet.readiness()
    assert status['network'] == 'test' and status['nu7_branch'] == '77190ad9'
    balance = wallet.balance()
    assert sum(balance['shielded_zatoshis'].values()) > 0
