"""Endpoint dekoratorleri.

Siralama (disaridan iceriye):
    @app.method -> @rate_limit -> @cache_response -> @retry -> @timeit -> @log

`cache_response` cache-aside pattern'i otomatik yonetir; yalnizca 200 donuslerde
yazar, exception durumunda cache'e dokunmaz. Yanit basliklarina `X-Cache`
(HIT/MISS) ve `X-Cache-TTL` eklenir.
"""

import asyncio
import functools
import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse

from src.cache import cache
from src.colorlogger import logger
from src.config import settings

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def client_ip(request: Request) -> str:
    """Ters vekil arkasindaki gercek istemci IP'sini dondurur."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip", "")
    if real:
        return real.strip()
    return request.client.host if request.client else "0.0.0.0"


def _find_request(args: tuple, kwargs: dict) -> Request | None:
    """Endpoint imzasindan `Request` nesnesini bulur."""
    candidate = kwargs.get("request")
    if isinstance(candidate, Request):
        return candidate
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None


def rate_limit(
    requests: int | None = None, window_seconds: int | None = None, scope: str = "global"
) -> Callable[[F], F]:
    """Sliding window rate limit. Varsayilanlar `.env`'den, endpoint bazinda override edilir."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _find_request(args, kwargs)
            if request is None or not cache.available:
                return await func(*args, **kwargs)

            limit = requests or settings.rate_limit_requests
            window = window_seconds or settings.rate_limit_window_seconds
            key = f"ratelimit:{scope}:{client_ip(request)}"
            hits = await cache.incr_window(key, window)
            if hits > limit:
                retry_after = max(await cache.ttl(key), 1)
                logger.warning(
                    "Rate limit asildi: ip=%s scope=%s hits=%s", client_ip(request), scope, hits
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Cok fazla istek gonderildi, lutfen biraz bekleyin.",
                    headers={"Retry-After": str(retry_after)},
                )
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def _build_cache_key(prefix: str, request: Request, vary_cookie: bool) -> str:
    """Istek yolundan + sorgu dizesinden deterministik cache anahtari uretir."""
    raw = f"{request.url.path}?{request.url.query}"
    if vary_cookie:
        raw += f"|{request.cookies.get(settings.session_cookie_name, '')}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"http:{prefix}:{digest}"


def okuma_sayaci(
    yol_parametresi: str, prefix: str = "okundu", pencere_saniye: int = 86400
) -> Callable[[F], F]:
    """Sayfa okunmasini ayni IP icin pencere basina bir kez sayar.

    **`cache_response`'un DISINDA** (ondan once) uygulanmalidir: onbellek isabet
    ettiginde endpoint govdesi hic calismaz, dolayisiyla govde icinde artirilan
    bir sayac onbellek suresince hic islemez.

    IP ham saklanmaz; JWT_SECRET ile tuzlanip kisaltilmis sha256'si tutulur.
    Amac sayim, kimlik degil.

    Args:
        yol_parametresi: Sayilacak kaydi belirleyen yol degiskeninin adi
            (ornek: "yazi_slug").
        prefix: Valkey anahtar oneki.
        pencere_saniye: Ayni IP'nin tekrar sayilmayacagi sure (varsayilan 1 gun).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _find_request(args, kwargs)
            deger = kwargs.get(yol_parametresi)

            if request is not None and deger:
                try:
                    tuz = f"{client_ip(request)}|{settings.jwt_secret}"
                    parmak = hashlib.sha256(tuz.encode()).hexdigest()[:20]
                    anahtar = f"{prefix}:{deger}:{parmak}"
                    if await cache.get_json(anahtar) is None:
                        await cache.set_json(anahtar, 1, pencere_saniye)
                        await repo_okuma_artir(deger)
                except Exception as exc:  # noqa: BLE001 — sayac istegi bozmamali
                    logger.warning("Okuma sayaci islenemedi (%s): %s", deger, exc)

            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


async def repo_okuma_artir(slug: str) -> None:
    """Sayaci artirir. Dairesel import olmasin diye repository gec yuklenir."""
    from src.models import repository as repo

    await repo.increment_view_by_slug(slug)


def cache_response(
    ttl: int | None = None, prefix: str = "page", vary_cookie: bool = False
) -> Callable[[F], F]:
    """Cache-aside dekoratoru — GET/liste/detay endpointlerinde zorunlu.

    Yalnizca 200 donuslerde yazar; exception olursa cache'e yazilmaz.
    Oturum acikken (panel) bypass edilir.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _find_request(args, kwargs)
            if request is None or not cache.available:
                return await func(*args, **kwargs)

            # Oturum acik kullanicilarda public cache kullanilmaz (taslak gorunurlugu)
            if not vary_cookie and request.cookies.get(settings.session_cookie_name):
                response = await func(*args, **kwargs)
                if isinstance(response, Response):
                    response.headers["X-Cache"] = "BYPASS"
                return response

            key = _build_cache_key(prefix, request, vary_cookie)
            cached = await cache.get_json(key)
            if cached is not None:
                remaining = await cache.ttl(key)
                headers = {
                    "X-Cache": "HIT",
                    "X-Cache-TTL": str(max(remaining, 0)),
                    "X-Data-Source": "valkey",
                }
                if cached.get("kind") == "html":
                    return HTMLResponse(
                        content=cached["body"], status_code=200, headers=headers
                    )
                return JSONResponse(content=cached["body"], status_code=200, headers=headers)

            result = await func(*args, **kwargs)
            expire = ttl or settings.cache_default_ttl

            if isinstance(result, HTMLResponse) and result.status_code == 200:
                await cache.set_json(
                    key, {"kind": "html", "body": result.body.decode()}, expire
                )
            elif isinstance(result, Response):
                if result.status_code == 200:
                    result.headers.setdefault("X-Cache", "MISS")
                return result
            else:
                await cache.set_json(key, {"kind": "json", "body": result}, expire)
                return JSONResponse(
                    content=result,
                    status_code=200,
                    headers={
                        "X-Cache": "MISS",
                        "X-Cache-TTL": str(expire),
                        "X-Data-Source": "postgres",
                    },
                )

            result.headers["X-Cache"] = "MISS"
            result.headers["X-Cache-TTL"] = str(expire)
            result.headers["X-Data-Source"] = "postgres"
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def retry(attempts: int = 2, delay: float = 0.2) -> Callable[[F], F]:
    """Gecici hatalarda endpoint govdesini yeniden dener (HTTPException haric)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except HTTPException:
                    raise
                except (OSError, ConnectionError, TimeoutError) as exc:
                    last_error = exc
                    logger.warning(
                        "%s deneme %s/%s basarisiz: %s", func.__name__, attempt, attempts, exc
                    )
                    if attempt < attempts:
                        await asyncio.sleep(delay * attempt)
            assert last_error is not None
            raise last_error

        return wrapper  # type: ignore[return-value]

    return decorator


def timeit(func: F) -> F:
    """Endpoint suresini olcer ve `request.state.timings` icine yazar."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            request = _find_request(args, kwargs)
            if request is not None:
                timings = getattr(request.state, "timings", None)
                if timings is None:
                    timings = {}
                    request.state.timings = timings
                timings[func.__name__[:24]] = round(elapsed_ms, 2)

    return wrapper  # type: ignore[return-value]


def log(func: F) -> F:
    """Endpoint girisini/cikisini ve hatalari logger ile kaydeder."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = _find_request(args, kwargs)
        ip = client_ip(request) if request else "-"
        path = request.url.path if request else func.__name__
        try:
            result = await func(*args, **kwargs)
        except HTTPException as exc:
            logger.warning("%s %s -> %s (%s)", ip, path, exc.status_code, exc.detail)
            raise
        except Exception as exc:  # noqa: BLE001 — yeniden firlatiliyor
            logger.exception("%s %s -> beklenmeyen hata: %s", ip, path, exc)
            raise
        return result

    return wrapper  # type: ignore[return-value]
