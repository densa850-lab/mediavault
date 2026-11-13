"""Security headers applied to every response, and a strict CORS middleware."""

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Send

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


_CORS_GRANT_HEADERS = ("access-control-allow-origin", "access-control-allow-credentials")


class StrictCORSMiddleware(CORSMiddleware):
    """Starlette's CORSMiddleware, but a disallowed origin gets no CORS grant at all.

    Upstream adds `Access-Control-Allow-Credentials: true` to every response that carries an
    Origin header, even when the origin is not allowed (MV-002). Browsers ignore it without
    Access-Control-Allow-Origin, but we strip it so untrusted origins receive neither header.
    """

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if not self.is_allowed_origin(origin=request_headers["origin"]):
            for name in _CORS_GRANT_HEADERS:
                if name in response.headers:
                    del response.headers[name]
        return response

    async def send(self, message: Message, send: Send, request_headers: Headers) -> None:
        origin = request_headers.get("origin")
        if origin is None or self.is_allowed_origin(origin=origin):
            await super().send(message, send, request_headers)
            return

        async def strip_and_send(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                headers = MutableHeaders(scope=msg)
                for name in _CORS_GRANT_HEADERS:
                    if name in headers:
                        del headers[name]
            await send(msg)

        await super().send(message, strip_and_send, request_headers)
