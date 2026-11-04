"""Isolated, ephemeral public demo. No real account/wallet adapters are reachable.

Each visitor receives random capabilities for a fresh temporary SQLite database.
The existing authenticated routes and spending engine run unchanged per session.
One worker only. Limits are intentionally in-memory; restart drops all demo data.
"""
import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import os
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.database import Base
from app.integrations.bitrefill import ProviderError
from app.schemas.bitrefill import Product, Denomination

TTL = 1800
MAX_SESSIONS = 100
MAX_BODY = 16384


class DemoCatalog:
    """Clearly labelled sample data, not a live account or paid purchase."""
    product = Product(id='swiggy-money-india', name='Sample Swiggy Money · DEMO ONLY',
                      country='IN', currency='INR', product_type='gift_card', available=True,
                      accepts_balance=True, denominations=[Denomination(package_value='50',
                      package_currency='INR', payment_price_cents=55, payment_currency='USD')])

    def search(self, query, intent, country='IN', product_type=None):
        return [self.product] if country == 'IN' and any(x in query.lower() for x in ('swiggy', 'gift', 'sample')) else []

    def details(self, product_id):
        if product_id != self.product.id:
            raise ProviderError('demo_product_not_found', 404)
        return self.product.model_copy(deep=True)

    def quote(self, *args):
        raise ProviderError('maximum_debit_unbounded', 503)

    def ensure_checkout_supported(self):
        raise ProviderError('public_demo_cannot_purchase', 403)

    def create_invoice(self, *args):
        raise ProviderError('public_demo_cannot_purchase', 403)

    def balance(self):
        raise ProviderError('public_demo_has_no_real_account', 403)

    def invoice(self, *args):
        raise ProviderError('public_demo_has_no_real_account', 403)


class DemoState:
    def __init__(self):
        self.sessions = {}
        self.tokens = {}
        self.windows = defaultdict(deque)
        self.lock = asyncio.Lock()

    def permit(self, key, limit, seconds):
        now = monotonic()
        window = self.windows[key]
        while window and window[0] < now - seconds:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def cleanup(self):
        now = monotonic()
        for sid, session in list(self.sessions.items()):
            if now > session['expires'] and session['inflight'] == 0:
                session['app'].state.database_engine.dispose()
                session['directory'].cleanup()
                for token in session['tokens']:
                    self.tokens.pop(token, None)
                self.sessions.pop(sid)
                self.windows.pop('session:' + sid, None)
        # Bound bookkeeping even if clients rotate source IPs.
        for key, values in list(self.windows.items()):
            if not values or values[-1] < now - 3600:
                self.windows.pop(key, None)

    def create(self):
        from app.main import create_app
        directory = TemporaryDirectory(prefix='zpermit-public-demo-')
        sid, owner, agent = token_urlsafe(24), token_urlsafe(32), token_urlsafe(32)
        settings = Settings(_env_file=None,
                            database_url=f'sqlite:///{Path(directory.name) / "demo.db"}',
                            dev_owner_id='demo-owner', dev_agent_id='demo-agent',
                            dev_owner_credential=SecretStr(owner), dev_agent_credential=SecretStr(agent),
                            BITREFILL_API_KEY=None, BITREFILL_LIVE_PURCHASES_ENABLED=False,
                            zcash_enabled=False, zcash_live_broadcast_enabled=False,
                            zcash_public_reads_enabled=False, public_demo=True)
        isolated = create_app(settings)
        isolated.state.bitrefill_provider = DemoCatalog()
        # REST/wallet routes are denied by the dispatcher before reaching the app.
        Base.metadata.create_all(isolated.state.database_engine)
        self.sessions[sid] = {'app': isolated, 'directory': directory,
                              'tokens': (owner, agent), 'expires': monotonic() + TTL, 'inflight': 0}
        self.tokens[owner] = self.tokens[agent] = sid
        return {'base': '', 'owner': owner, 'agent': agent, 'demo': True, 'expires_in_seconds': TTL}


def create_demo_app():
    # Fail closed if someone tries to attach actual credentials to public hosting.
    forbidden = ('BITREFILL_API_KEY', 'ZPERMIT_BITREFILL_API_KEY',
                 'ZPERMIT_DEV_OWNER_CREDENTIAL', 'ZPERMIT_DEV_AGENT_CREDENTIAL',
                 'ZPERMIT_ZCASH_ZALLET_CONFIG', 'ZPERMIT_ZCASH_ZALLET_DATADIR')
    if any(os.environ.get(key, '').strip() for key in forbidden):
        raise RuntimeError('Public demo must not be configured with private account or wallet credentials')
    state = DemoState()

    @asynccontextmanager
    async def lifespan(app):
        yield
        for session in state.sessions.values():
            session['app'].state.database_engine.dispose()
            session['directory'].cleanup()

    outer = FastAPI(title='ZPermit isolated public demo', docs_url=None, redoc_url=None,
                    openapi_url=None, lifespan=lifespan)
    outer.state.demo = state

    @outer.middleware('http')
    async def dispatch(request: Request, call_next):
        path = request.url.path
        # Public routes return no account or private workspace data.
        if path.startswith('/api/'):
            peer = request.client.host if request.client else 'unknown'
            async with state.lock:
                state.cleanup()
                if len(state.windows) >= 3000 and 'ip:' + peer not in state.windows:
                    return JSONResponse(status_code=429, content={'detail': 'Demo capacity reached; try later'})
                if not state.permit('global', 300, 60) or not state.permit('ip:' + peer, 120, 60):
                    return JSONResponse(status_code=429, content={'detail': 'Demo rate limit; try again later'}, headers={'Retry-After':'60'})
            size = 0
            chunks = []
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    chunks.append(chunk)
                    if size > MAX_BODY:
                        return JSONResponse(status_code=413, content={'detail':'Demo request body too large'})
                # Replay a bounded body through Starlette's cached request wrapper.
                request._body = b''.join(chunks)
            except RuntimeError:
                return JSONResponse(status_code=400, content={'detail':'Invalid request'})
        return await call_next(request)

    @outer.get('/health')
    def health():
        return {'status':'ok', 'service':'zpermit', 'mode':'public_demo'}

    @outer.get('/api/mode')
    def mode():
        return {'mode':'public_demo', 'sample_data':True, 'can_spend':False, 'session_ttl_seconds':TTL}

    @outer.post('/api/demo/sessions')
    async def session(request: Request):
        peer = request.client.host if request.client else 'unknown'
        async with state.lock:
            state.cleanup()
            if len(state.sessions) >= MAX_SESSIONS or not state.permit('new:' + peer, 12, 600):
                return JSONResponse(status_code=429, content={'detail':'Demo session limit; try again later'}, headers={'Retry-After':'600'})
            data = await run_in_threadpool(state.create)
        return JSONResponse(data, headers={'Cache-Control':'no-store'})

    @outer.api_route('/api/{path:path}', methods=['GET','POST','PUT','DELETE','PATCH','OPTIONS'])
    async def proxy(path: str, request: Request):
        auth = request.headers.get('authorization', '')
        token = auth[7:] if auth.startswith('Bearer ') else ''
        async with state.lock:
            sid = state.tokens.get(token)
            session = state.sessions.get(sid)
            if not session or monotonic() > session['expires']:
                return JSONResponse(status_code=401, content={'detail':'Demo session missing or expired; start a new isolated session'})
            if not state.permit('session:' + sid, 90, 60):
                return JSONResponse(status_code=429, content={'detail':'Demo session rate limit'}, headers={'Retry-After':'60'})
            # No provider account records, invoices, executions, wallet or chain routes.
            allowed = (path in {'workspace', 'workspace/identity', 'permits', 'purchase-requests', 'bitrefill/products', 'bitrefill/purchase-previews'}
                       or path.startswith(('permits/', 'purchase-requests/', 'bitrefill/products/')))
            if not allowed:
                return JSONResponse(status_code=403, content={'detail':'Public demo: real accounts, invoices, payments and wallet access are disabled'})
            session['inflight'] += 1
        messages = []
        body = await request.body()
        received = False
        async def receive():
            nonlocal received
            if not received:
                received = True
                return {'type':'http.request', 'body':body, 'more_body':False}
            await asyncio.sleep(3600)
            return {'type':'http.disconnect'}
        async def send(message):
            messages.append(message)
        try:
            await session['app'](dict(request.scope), receive, send)
        finally:
            async with state.lock:
                session['inflight'] -= 1
        from starlette.responses import Response
        start = next(m for m in messages if m['type'] == 'http.response.start')
        content = b''.join(m.get('body', b'') for m in messages if m['type']=='http.response.body')
        response = Response(content, status_code=start['status'])
        response.raw_headers = [(k,v) for k,v in start['headers'] if k.lower() not in {b'content-length', b'cache-control'}]
        response.headers['Cache-Control'] = 'no-store'
        return response

    # Only safe GET navigation falls back to the SPA. /api is always handled above.
    dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    if (dist / 'assets').is_dir():
        outer.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    @outer.get('/{path:path}', include_in_schema=False)
    def frontend(path: str):
        if path.startswith(('api', 'assets', '.')) or not (dist/'index.html').is_file():
            return JSONResponse(status_code=404, content={'detail':'Not found'})
        return FileResponse(dist/'index.html', headers={'Cache-Control':'no-cache'})
    return outer
