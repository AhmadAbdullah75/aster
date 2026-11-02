from fastapi import HTTPException

from .config import settings


class BodyLimitMiddleware:
    """Count streamed bytes too; a missing Content-Length cannot bypass body limits."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        maximum = (
            (settings.upload_limit_mib + 1) * 1024 * 1024
            if scope.get("path") == "/documents"
            else 512 * 1024
        )
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > maximum:
                raise HTTPException(413, "Request body too large.")
            return message

        await self.app(scope, bounded_receive, send)
