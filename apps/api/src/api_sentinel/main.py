import json
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint

from api_sentinel.health import database_ready


class Health(BaseModel):
    status: Literal["ok", "ready", "unavailable"]


def create_app(probe: Callable[[], Awaitable[bool]] = database_ready) -> FastAPI:
    app = FastAPI(title="API Sentinel", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def record_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid4().hex
        started = monotonic()
        response = await call_next(request)
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
