"""Operator-controlled admission for one backend process during a release."""

import hmac
import os

from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from app.config import settings
from app.web_security import error


BARRIER_HEADER = "X-Release-Barrier-Token"


class ReleaseBarrier:
    def __init__(self, app):
        self.app = app
        self.in_flight = 0

    async def __call__(self, scope, receive, send):
        file = settings.RELEASE_BARRIER_STATE_FILE
        if scope["type"] != "http" or not file:
            await self.app(scope, receive, send)
            return

        path = get_route_path(scope)
        if scope["method"] == "GET" and path in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        try:
            with open(file, "rb") as state:
                mode = {b"open\n": "open", b"bot-only\n": "bot-only"}.get(state.read(16), "closed")
        except OSError:
            mode = "closed"

        supplied = Headers(scope=scope).getlist(BARRIER_HEADER)
        token = settings.RELEASE_BARRIER_TOKEN.get_secret_value()
        authorized = bool(token) and len(supplied) == 1 and hmac.compare_digest(
            token.encode(), supplied[0].encode()
        )
        if path == "/internal/release/barrier":
            if authorized and scope["method"] == "GET":
                response = JSONResponse(
                    {"mode": mode, "in_flight": self.in_flight, "pid": os.getpid()},
                    headers={"Cache-Control": "no-store"},
                )
            else:
                response = JSONResponse({"detail": "Not Found"}, status_code=404)
            await response(scope, receive, send)
            return

        if mode == "closed" or (mode == "bot-only" and not authorized):
            if path == "/v2" or path.startswith("/v2/"):
                response = error(503, "temporarily_unavailable")
            else:
                response = JSONResponse({"detail": "release_maintenance"}, status_code=503)
            response.headers["Retry-After"] = "30"
            response.headers["Cache-Control"] = "no-store"
            await response(scope, receive, send)
            return

        self.in_flight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_flight -= 1
