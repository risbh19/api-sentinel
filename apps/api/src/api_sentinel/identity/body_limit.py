from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AccessBodyLimit:
    """Limit input as it is read, including requests without a Content-Length."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return
        size = 0

        async def limited_receive() -> Message:
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 16384:
                raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)
