"""Opt-in REAL public-testnet reads. No wallet control or broadcasting."""
import os
import pytest
from app.core.config import Settings
from app.integrations.public_testnet import PublicTestnetClient


@pytest.mark.skipif(os.environ.get('ZPERMIT_RUN_PUBLIC_TESTNET_READS')!='1',reason='Explicit opt-in required for real public lightwallet RPCs')
def test_live_nu7_ironwood_public_service():
    c=PublicTestnetClient(Settings().model_copy(update={'zcash_public_reads_enabled':True}))
    r=c.readiness()
    assert r['ready'] and r['network']=='test' and r['nu7_branch']=='77190ad9'
    assert not r['signing_supported']
