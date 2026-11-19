from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="API Sentinel",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
    redirect_slashes=False,
)


class Liveness(BaseModel):
    status: Literal["ok"]


@app.get("/health/live")
async def liveness() -> Liveness:
    """Report that this process can handle a request."""
    return Liveness(status="ok")
