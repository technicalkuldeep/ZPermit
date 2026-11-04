import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi.staticfiles import StaticFiles

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.exc import OperationalError

from app.api.workspace import router as workspace_router
from app.integrations.verify_bitrefill_rest import RestAccessVerifier

from app.api.mobile_payment import router as mobile_payment_router
from app.api.public_testnet import router as public_testnet_router
from app.integrations.public_testnet import PublicTestnetClient

from app.api.zcash import router as zcash_router
from app.integrations.zcash import ZalletAdapter, ZcashError

from app.api.health import router as health_router
from app.api.spending import router as spending_router
from app.api.bitrefill import router as bitrefill_router
from app.core.config import Settings, get_settings
from app.core.database import create_database_engine
from app.services.spending import DomainError
from app.integrations.bitrefill import BitrefillClient, ProviderError


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()
    engine = create_database_engine(config.database_url)

    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="ZPermit API", version="0.2.0", lifespan=lifespan)
    application.state.settings = config
    application.state.database_engine = engine
    application.state.bitrefill_provider = BitrefillClient(config)
    application.state.bitrefill_rest_reader = RestAccessVerifier(config)
    application.state.zcash_wallet = ZalletAdapter(config)
    application.state.public_testnet = PublicTestnetClient(config)

    @application.exception_handler(ZcashError)
    async def zcash_error(request: Request, exc: ZcashError):
        return JSONResponse(status_code=503, content={"detail": {"code": exc.code,
                            "message": "Zcash testnet wallet request could not be completed"}})

    @application.exception_handler(ProviderError)
    async def provider_error(request: Request, exc: ProviderError):
        return JSONResponse(status_code=exc.status_code, content={
            "detail": {"code": exc.code, "message": "Bitrefill request could not be completed"},
        })

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @application.exception_handler(OperationalError)
    async def database_error(request: Request, exc: OperationalError):
        # Do not disclose connection strings, SQL statements or bound values.
        return JSONResponse(status_code=503, content={"detail": "Database unavailable; retry later"})

    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type", "Authorization"],
    )
    @application.get('/api/mode', tags=['Application mode'])
    def mode():
        return {'mode': 'private_local', 'sample_data': False, 'can_spend': False}

    application.include_router(workspace_router)
    application.include_router(mobile_payment_router)
    application.include_router(public_testnet_router)
    application.include_router(zcash_router)
    application.include_router(health_router)
    application.include_router(spending_router)
    application.include_router(bitrefill_router)
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        # Serve only the app shell/assets. Unknown /api routes must stay JSON 404s.
        @application.get("/overview", include_in_schema=False)
        @application.get("/permits", include_in_schema=False)
        @application.get("/shop", include_in_schema=False)
        @application.get("/requests", include_in_schema=False)
        @application.get("/payments", include_in_schema=False)
        @application.get("/evidence", include_in_schema=False)
        @application.get("/connection", include_in_schema=False)
        @application.get("/", include_in_schema=False)
        def frontend_index():
            return FileResponse(frontend_dist / "index.html", headers={"Cache-Control": "no-cache"})

        if (frontend_dist / "assets").is_dir():
            application.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")
    return application


# A public demo process must never load the private local .env as a side effect.
app = (create_app(Settings(_env_file=None, database_url='sqlite://',
                       BITREFILL_API_KEY=None, BITREFILL_LIVE_PURCHASES_ENABLED=False,
                       dev_owner_credential=None, dev_agent_credential=None,
                       zcash_enabled=False, zcash_live_broadcast_enabled=False,
                       zcash_public_reads_enabled=False))
       if os.environ.get('ZPERMIT_PUBLIC_DEMO', '').lower() in {'1', 'true'} else create_app())
