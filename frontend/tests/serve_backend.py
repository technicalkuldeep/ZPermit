"""Real application, isolated data, no wallet or provider write capability enabled."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uvicorn
from app.core.config import get_settings
from app.core.database import Base
from app.main import create_app

with TemporaryDirectory(prefix='zpermit-browser-') as temp:
    settings = get_settings().model_copy(update={
        'database_url':f'sqlite:///{Path(temp) / "browser.db"}',
        'dev_owner_credential':__import__('pydantic').SecretStr(os.environ['ZPERMIT_BROWSER_OWNER']),
        'dev_agent_credential':__import__('pydantic').SecretStr(os.environ['ZPERMIT_BROWSER_AGENT']),
        'bitrefill_live_purchases_enabled':False,
        'zcash_live_broadcast_enabled':False,
        'zcash_enabled':False,
        'zcash_public_reads_enabled':True,
    })
    app=create_app(settings)
    Base.metadata.create_all(app.state.database_engine)
    uvicorn.run(app,host='127.0.0.1',port=8011,access_log=False,log_level='warning')
