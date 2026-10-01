"""Cap actual HTTP bytes, including chunked bodies without Content-Length."""

import asyncio
from fastapi import HTTPException
from starlette.responses import JSONResponse


class RequestLimit:
    def __init__(self, app, max_upload_mb=100):
        self.app, self.max_upload_mb = app, max_upload_mb

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        cap = 256 * 1024
        if path.endswith("/upload"):
            cap = (
                11 if path.startswith("/api/conversations/") else self.max_upload_mb + 1
            ) * 1024**2
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid length"}, 400)(
                scope, receive, send
            )
        if length < 0 or length > cap:
            return await JSONResponse({"detail": "Request too large"}, 413)(
                scope, receive, send
            )
        size = 0
        deadline = asyncio.get_running_loop().time() + 60

        async def limited():
            nonlocal size
            try:
                message = await asyncio.wait_for(
                    receive(), max(0.001, deadline - asyncio.get_running_loop().time())
                )
            except asyncio.TimeoutError:
                raise HTTPException(408, "Upload timeout") from None
            size += len(message.get("body", b""))
            if size > cap:
                raise HTTPException(413, "Request too large")
            return message

        return await self.app(scope, limited, send)
