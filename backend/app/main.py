from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

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
    application.include_router(health_router)
    application.include_router(spending_router)
    application.include_router(bitrefill_router)
    return application


app = create_app()
