"""gokhancoskun.com — FastAPI uygulama girisi.

Public site (SSR), yonetim paneli ve REST API tek uygulamada sunulur.
Nginx apex alan adini ve panel alt alan adini ayni surece proxy'ler.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.cache import cache
from src.colorlogger import logger
from src.config import settings
from src.db import db
from src.middleware import ObservabilityMiddleware, SecurityHeadersMiddleware
from src.models import repository as repo
from src.routers import api, panel, public
from src.templating import ASSET_VERSION, templates

BASE_DIR = Path(__file__).resolve().parent
MIGRATION_DIR = BASE_DIR / "migrations"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Acilista baglantilari kurar ve migration'lari uygular, kapanista kapatir."""
    db.connect()
    cache.connect()

    if not await db.healthy():
        logger.error("PostgreSQL baglantisi kurulamadi — uygulama yine de baslatiliyor")
    else:
        # Advisory lock: birden fazla gunicorn worker'i ayni anda migration
        # calistirmasin (ayni sema uzerinde yaris kosulu olusur).
        for dosya in sorted(MIGRATION_DIR.glob("*.sql")):
            try:
                await db.execute_script(
                    dosya.read_text(encoding="utf-8"), lock_key=8021_2026
                )
                logger.info("Migration uygulandi: %s", dosya.name)
            except Exception as exc:  # noqa: BLE001 — migration hatasi loglanip gecilir
                logger.error("Migration basarisiz (%s): %s", dosya.name, exc)

        # Yonetici hesabi olusturma acilisi ENGELLEMEMELI — migration bir
        # onceki adimda basarisiz olduysa burada tablo yoktur.
        try:
            await repo.ensure_admin_user()
        except Exception as exc:  # noqa: BLE001 — acilis surmeli
            logger.error("Yonetici hesabi olusturulamadi: %s", exc)

    if await cache.healthy():
        logger.info("Valkey baglantisi hazir")
    else:
        logger.warning("Valkey erisilemiyor — cache devre disi, istekler DB'ye gider")

    logger.info("Uygulama hazir: %s (ortam=%s)", settings.site_url, settings.app_env)
    yield

    await cache.disconnect()
    await db.disconnect()
    logger.info("Uygulama kapatildi")


app = FastAPI(
    title="gokhancoskun.com",
    description=(
        "Kişisel site, blog ve yönetim paneli.\n\n"
        "**API kullanımı:** Panelden üretilen token ile "
        "`Authorization: Bearer <token>` başlığı gönderin. "
        "MCP sunucusu bu API üzerinden yazı ekler."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={"docExpansion": "none", "persistAuthorization": True},
)

# Middleware sirasi: en son eklenen en dista calisir.
# Istek: Security -> Observability -> router
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(SecurityHeadersMiddleware, enable_hsts=not settings.debug)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_media_dir = Path(settings.media_root)
if not _media_dir.is_absolute():
    _media_dir = BASE_DIR / _media_dir
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


# ------------------------------------------------------------------
# Hata isleyicileri — HTML sayfalarda sablon, API'de JSON dondurur
# ------------------------------------------------------------------
def _api_istegi_mi(request: Request) -> bool:
    """Istegin JSON yanit bekleyip beklemedigini belirler."""
    if request.url.path.startswith("/api/"):
        return True
    return "application/json" in request.headers.get("accept", "")


@app.exception_handler(StarletteHTTPException)
async def http_hata(request: Request, exc: StarletteHTTPException):
    """HTTP hatalarini uygun formatta dondurur."""
    if _api_istegi_mi(request):
        return JSONResponse(
            status_code=exc.status_code,
            content={"hata": exc.detail, "kod": exc.status_code},
            headers=getattr(exc, "headers", None),
        )

    # Panel sayfalarinda oturum yoksa giris ekranina yonlendir
    if exc.status_code == 401 and request.url.path.startswith("/panel"):
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/giris", status_code=303)

    basliklar = {
        404: ("Sayfa bulunamadı", "Aradığınız sayfa taşınmış veya kaldırılmış olabilir."),
        403: ("Erişim reddedildi", "Bu sayfayı görüntüleme yetkiniz yok."),
        429: ("Çok fazla istek", "Kısa sürede çok fazla istek gönderdiniz. Lütfen biraz bekleyin."),
        500: ("Bir şeyler ters gitti", "Sunucuda beklenmeyen bir hata oluştu."),
    }
    baslik, aciklama = basliklar.get(
        exc.status_code, ("Bir hata oluştu", str(exc.detail) or "Beklenmeyen bir durum oluştu.")
    )

    try:
        profil = await repo.get_profile()
        menu = await repo.list_pages(menu_only=True)
    except Exception:  # noqa: BLE001 — DB kapaliyken de hata sayfasi gosterilmeli
        profil = {"full_name": "Gökhan Coşkun", "tagline": "", "avatar_url": None, "socials": {}}
        menu = []

    return templates.TemplateResponse(
        request=request,
        name="hata.html",
        context={
            "request": request,
            "profil": profil,
            "menu_sayfalari": menu,
            "site_url": settings.site_url.rstrip("/"),
            "panel_url": settings.panel_url.rstrip("/"),
            "asset_version": ASSET_VERSION,
            "yil": __import__("datetime").datetime.now().year,
            "aktif": "",
            "kod": exc.status_code,
            "baslik": baslik,
            "aciklama": aciklama,
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def dogrulama_hatasi(request: Request, exc: RequestValidationError):
    """Pydantic dogrulama hatalarini okunabilir formatta dondurur."""
    logger.warning("Dogrulama hatasi: %s %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "hata": "Gönderilen veri geçersiz",
            "kod": 422,
            "detaylar": [
                {"alan": ".".join(str(p) for p in e["loc"][1:]), "mesaj": e["msg"]}
                for e in exc.errors()
            ],
        },
    )


# ------------------------------------------------------------------
# Saglik kontrolu
# ------------------------------------------------------------------
@app.get("/saglik", tags=["Sistem"], summary="Sağlık kontrolü")
async def saglik() -> JSONResponse:
    """Servis, veritabani ve cache durumunu dondurur."""
    postgres_ok = await db.healthy()
    valkey_ok = await cache.healthy()
    durum = "saglikli" if postgres_ok else "bozuk"
    return JSONResponse(
        status_code=200 if postgres_ok else 503,
        content={
            "durum": durum,
            "postgres": postgres_ok,
            "valkey": valkey_ok,
            "surum": app.version,
            "ortam": settings.app_env,
        },
    )


# ------------------------------------------------------------------
# Router'lar — sirasi onemli:
#   api ve panel ONCE gelir; public router'daki /{sayfa_slug} catch-all
#   aksi halde /panel, /giris gibi yollari yutar.
# ------------------------------------------------------------------
app.include_router(api.router)
app.include_router(panel.router)
app.include_router(public.router)


# ------------------------------------------------------------------
# GET tanimlanan her yola HEAD de eklenir.
#
# Starlette'in `Route` sinifi bunu kendiliginden yapar; FastAPI'nin
# `APIRoute`'u YAPMAZ — `@router.get(...)` yalnizca GET kaydeder. Sonuc:
# butun site HEAD isteklerine 405 doner. Bundan etkilenenler: calisma
# suresi izleyicileri, bag denetleyicileri ve dosyayi once HEAD ile
# yoklayan bazi tarayicilar (ornegin sitemap cekicileri).
#
# Govde HEAD yanitinda gonderilmez; bunu HTTP katmani (h11/uvicorn)
# istegin metoduna bakarak halleder.
# ------------------------------------------------------------------
def _head_destegi_ekle(uygulama: FastAPI) -> None:
    """Yalnizca GET kabul eden route'lara HEAD metodunu ekler."""
    for route in uygulama.routes:
        metotlar = getattr(route, "methods", None)
        if metotlar == {"GET"}:
            route.methods = {"GET", "HEAD"}


_head_destegi_ekle(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
