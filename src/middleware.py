"""Middleware katmani — Server-Timing, guvenlik basliklari ve istek kimligi."""

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from src.colorlogger import logger
from src.config import settings
from src.decorators import client_ip

# Satir ici tema onyukleyicisinin sha256 karmasi.
# NOT: nonce yerine hash kullaniliyor — cache_response HTML govdesini
# onbellege aldigi icin nonce ikinci istekte bayatlar ve script bloklanirdi.
# templates/partials/tema_onyukleyici.html degisirse:
#   python3 scripts/csp_hash.py
_INLINE_SCRIPT_HASH = "'sha256-VPtWLhJ+rAMMZRasHJC4KJnD7RyYGvXNrNYNHuS0lbA='"

_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    # style-src: sablonlarda birkac satir ici `style=""` var; 'unsafe-inline'
    # yalnizca stil icin acik, script icin DEGIL.
    "style-src 'self' 'unsafe-inline'; "
    f"script-src 'self' {_INLINE_SCRIPT_HASH}; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "media-src 'self' blob:"
)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Server-Timing, X-Request-ID ve X-Data-Source basliklarini ekler."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Istegi olcer ve zamanlama basliklarini yanita ekler."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        request.state.timings = {}
        started = time.perf_counter()

        response = await call_next(request)

        total_ms = (time.perf_counter() - started) * 1000
        parts = [f'app;dur={total_ms:.2f};desc="toplam"']
        for name, value in request.state.timings.items():
            parts.append(f"{name};dur={value}")
        response.headers["Server-Timing"] = ", ".join(parts)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Cache", "MISS")
        response.headers.setdefault("X-Data-Source", "postgres")

        if total_ms > 1000:
            logger.warning(
                "Yavas istek: %s %s %.0fms (ip=%s)",
                request.method,
                request.url.path,
                total_ms,
                client_ip(request),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """OWASP onerileri dogrultusunda guvenlik basliklarini ekler."""

    def __init__(self, app: ASGIApp, enable_hsts: bool = True) -> None:
        super().__init__(app)
        self.enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Yanit basliklarina guvenlik politikalarini yazar."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), interest-cohort=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers.setdefault("Content-Security-Policy", _CSP)
        if self.enable_hsts and not settings.debug:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response
