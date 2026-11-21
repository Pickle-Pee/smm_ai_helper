"""Browser trust boundary for /v2 only."""
import base64
import hashlib
import hmac
import ipaddress
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import get_session
from app.models import WebSession
from app.services import web_auth, web_me

SESSION = "__Host-brenvio_session"
ATTEMPT = "__Host-brenvio_attempt"
SAFE = {"GET", "HEAD", "OPTIONS"}
CACHE_CONTROL = "private, no-store"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"


class WebFailure(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


def error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"schema_version": "web_api.v2", "kind": "ERROR", "code": code,
                         "request_id": uuid.uuid4().hex}, status_code=status,
                        headers={"Cache-Control": CACHE_CONTROL})


def origin_key(value: str):
    # Accept a serialized HTTPS origin only. Reject URL parser normalization of
    # credentials, controls, backslashes, empty query/fragment, or a trailing path.
    if not re.fullmatch(r"https://(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?", value):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if ":" in host:
            host = str(ipaddress.IPv6Address(host))
        elif len(host) > 253 or not all(re.fullmatch(_LABEL, label) for label in host.split(".")):
            return None
        if parts.port == 0:
            return None
        return host, parts.port or 443
    except ValueError:
        return None


def valid_config():
    secret = settings.WEB_CSRF_SECRET.get_secret_value()
    return (origin_key(settings.WEB_APP_ORIGIN) is not None and len(secret.encode()) >= 32
            and secret != settings.BOT_BACKEND_TOKEN)


def check_origin(request: Request):
    origins = request.headers.getlist("origin")
    sites = request.headers.getlist("sec-fetch-site")
    if sites and sites != ["same-origin"]:
        raise WebFailure(403, "csrf_failed")
    if origins:
        if len(origins) == 1 and origin_key(origins[0]) == origin_key(settings.WEB_APP_ORIGIN):
            return
    elif sites == ["same-origin"]:
        return
    raise WebFailure(403, "csrf_failed")


def csrf(row: WebSession) -> str:
    key = settings.WEB_CSRF_SECRET.get_secret_value().encode()
    message = b"brenvio/web-csrf/v1\x00" + bytes.fromhex(row.token_hash)
    return base64.urlsafe_b64encode(hmac.digest(key, message, hashlib.sha256)).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class WebPrincipal:
    session: WebSession

    @property
    def user_id(self) -> int:
        return self.session.user_id


async def optional_principal(request: Request, db: AsyncSession = Depends(get_session)) -> WebPrincipal | None:
    cookie = request.cookies.get(SESSION)
    row = await web_auth.authenticate(db, cookie) if cookie else None
    if row is None:
        return None
    if request.method not in SAFE:
        headers = request.headers.getlist("x-csrf-token")
        if len(headers) != 1 or not hmac.compare_digest(headers[0].encode(), csrf(row).encode()):
            raise WebFailure(403, "csrf_failed")
    return WebPrincipal(row)


async def require_web_session(principal: WebPrincipal | None = Depends(optional_principal)) -> WebPrincipal:
    if principal is None:
        raise WebFailure(401, "unauthenticated")
    return principal


class WebBoundary(BaseHTTPMiddleware):
    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/v2" or path.startswith("/v2/")):
            await super().__call__(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not settings.WEB_API_ENABLED:
            return error(404, "not_found")
        try:
            if not valid_config():
                return error(503, "temporarily_unavailable")
            if any(name in request.headers for name in ("authorization", "x-telegram-user-id", "x-bot-backend-token")):
                return error(401, "unauthenticated")
            if request.method not in SAFE:
                check_origin(request)
            if path.startswith("/v2/auth/telegram/") and not settings.WEB_TELEGRAM_LOGIN_ENABLED:
                return error(403, "feature_disabled")
            response = await call_next(request)
            # FastAPI validation details can contain the raw rejected input. Never
            # forward those or slash redirects (Location would repeat the query).
            if response.status_code == 422:
                return error(422, "invalid_request")
            if response.status_code in (307, 404):
                return error(404, "not_found")
            if response.status_code == 405:
                return error(405, "invalid_request")
        except WebFailure as exc:
            return error(exc.status, exc.code)
        except web_auth.InvalidLogin:
            return error(401, "login_token_invalid")
        except web_me.OnboardingUnavailable:
            return error(503, "temporarily_unavailable")
        except Exception:
            # Driver, commit and serialization errors can carry sensitive values.
            return error(503, "temporarily_unavailable")
        response.headers["Cache-Control"] = CACHE_CONTROL
        return response
