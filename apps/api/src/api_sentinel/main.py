import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.middleware.base import RequestResponseEndpoint

from api_sentinel.audit.routes import router as audit_router
from api_sentinel.database import open_engine
from api_sentinel.health import database_ready
from api_sentinel.identity.body_limit import AccessBodyLimit
from api_sentinel.identity.routes import router
from api_sentinel.identity.security import web_origin
from api_sentinel.ingestion.routes import router as key_router
from api_sentinel.inventory.routes import router as inventory_router


class Health(BaseModel):
    status: Literal["ok", "ready", "unavailable"]


def create_app(
    probe: Callable[[], Awaitable[bool]] = database_ready, *, engine: Engine | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = engine
        if pool is None and os.environ.get("SENTINEL_APP_PASSWORD"):
            pool = open_engine(application=True)
        app.state.access_engine = pool
        try:
            yield
        finally:
            if pool is not None and engine is None:
                pool.dispose()

    app = FastAPI(title="API Sentinel", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.web_origin = web_origin()
    app.include_router(router)
    app.include_router(audit_router)
    app.include_router(inventory_router)
    app.include_router(key_router)
    app.add_middleware(AccessBodyLimit)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default payload may echo rejected passwords.
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.exception_handler(DBAPIError)
    @app.exception_handler(PoolTimeout)
    async def storage_unavailable(request: Request, exc: DBAPIError | PoolTimeout) -> JSONResponse:
        return JSONResponse({"detail": "Database operation unavailable"}, status_code=503)

    @app.middleware("http")
    async def record_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = monotonic()
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        logging.getLogger("uvicorn.error").info(
            json.dumps(
                {
                    "request_id": request_id,
                    "route": getattr(route, "path", "unmatched"),
                    "status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000),
                }
            )
        )
        return response

    @app.get("/health/live")
    async def live(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        return Health(status="ok")

    @app.get("/health/ready", responses={503: {"model": Health}})
    async def ready(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        if await probe():
            return Health(status="ready")
        response.status_code = 503
        return Health(status="unavailable")

    return app
