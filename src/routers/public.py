"""Public SSR sayfalari: anasayfa, blog, etiket, statik sayfalar, sitemap."""

import math
from datetime import UTC, datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import ValidationError

from src.colorlogger import logger
from src.config import settings
from src.decorators import cache_response, client_ip, log, rate_limit, retry, timeit
from src.models import repository as repo
from src.models.schemas import ContactCreate, PostStatus
from src.services.bot_koruma import FormTokenHatasi, form_tokeni_dogrula, form_tokeni_uret
from src.services.mail_service import iletisim_bildirimi_gonder
from src.services.markdown_service import plain_text
from src.templating import kirinti, temel_baglam, templates

router = APIRouter(tags=["Public"])

YAZI_SAYFA_BOYUTU = 9


def _hata_sayfasi(request: Request, baglam: dict, kod: int, baslik: str, aciklama: str) -> HTMLResponse:
    """Ortak hata sayfasi yaniti uretir."""
    return templates.TemplateResponse(
        request=request,
        name="hata.html",
        context={**baglam, "kod": kod, "baslik": baslik, "aciklama": aciklama},
        status_code=kod,
    )


# ==================================================================
# Anasayfa
# ==================================================================
@router.get("/", response_class=HTMLResponse, summary="Anasayfa")
@rate_limit(scope="public")
@cache_response(ttl=300, prefix="anasayfa")
@retry(attempts=2)
@timeit
@log
async def anasayfa(request: Request) -> HTMLResponse:
    """Kisisel tanitim, one cikan ve son yazilari gosterir."""
    baglam = await temel_baglam(request, aktif="anasayfa")
    one_cikanlar, _ = await repo.list_posts(
        page=1, per_page=3, status=PostStatus.PUBLISHED, featured_only=True
    )
    son_yazilar, _ = await repo.list_posts(page=1, per_page=6, status=PostStatus.PUBLISHED)
    one_cikan_slugs = {y["slug"] for y in one_cikanlar}
    son_yazilar = [y for y in son_yazilar if y["slug"] not in one_cikan_slugs][:6]

    return templates.TemplateResponse(
        request=request,
        name="anasayfa.html",
        context={**baglam, "one_cikanlar": one_cikanlar, "son_yazilar": son_yazilar},
    )


# ==================================================================
# Blog listesi
# ==================================================================
@router.get("/blog", response_class=HTMLResponse, summary="Blog yazi listesi")
@rate_limit(scope="public")
@cache_response(ttl=180, prefix="blog")
@retry(attempts=2)
@timeit
@log
async def blog_listesi(
    request: Request,
    sayfa: int = Query(default=1, ge=1, le=1000, description="Sayfa numarası"),
    ara: str | None = Query(default=None, max_length=100, description="Arama terimi"),
) -> HTMLResponse:
    """Yayindaki yazilari sayfalayarak listeler; arama destekler."""
    baglam = await temel_baglam(request, aktif="blog")
    yazilar, toplam = await repo.list_posts(
        page=sayfa, per_page=YAZI_SAYFA_BOYUTU, status=PostStatus.PUBLISHED, search=ara
    )
    toplam_sayfa = max(1, math.ceil(toplam / YAZI_SAYFA_BOYUTU))
    site = baglam["site_url"]

    return templates.TemplateResponse(
        request=request,
        name="blog_liste.html",
        context={
            **baglam,
            "baslik": "Blog",
            "aciklama": f"{baglam['profil']['full_name']} tarafından yazılan tüm yazılar.",
            "yazilar": yazilar,
            "sayfa": sayfa,
            "toplam_sayfa": toplam_sayfa,
            "taban": "/blog",
            "arama": ara,
            "etiketler": await repo.list_tags(limit=20),
            "kirinti_ogeleri": kirinti(("Anasayfa", f"{site}/"), ("Blog", f"{site}/blog")),
        },
    )


# ==================================================================
# Etiket sayfasi
# ==================================================================
@router.get("/etiket/{etiket_slug}", response_class=HTMLResponse, summary="Etikete göre yazılar")
@rate_limit(scope="public")
@cache_response(ttl=180, prefix="etiket")
@retry(attempts=2)
@timeit
@log
async def etiket_sayfasi(
    request: Request,
    etiket_slug: str,
    sayfa: int = Query(default=1, ge=1, le=1000),
) -> HTMLResponse:
    """Belirli bir etikete sahip yayindaki yazilari listeler."""
    baglam = await temel_baglam(request, aktif="blog")
    yazilar, toplam = await repo.list_posts(
        page=sayfa, per_page=YAZI_SAYFA_BOYUTU, status=PostStatus.PUBLISHED, tag=etiket_slug
    )
    if not yazilar and sayfa == 1:
        return _hata_sayfasi(
            request, baglam, 404, "Etiket bulunamadı",
            "Bu etikete sahip yayınlanmış bir yazı yok.",
        )

    etiket_adi = next(
        (t["name"] for t in await repo.list_tags(limit=200) if t["slug"] == etiket_slug),
        etiket_slug,
    )
    toplam_sayfa = max(1, math.ceil(toplam / YAZI_SAYFA_BOYUTU))
    site = baglam["site_url"]

    return templates.TemplateResponse(
        request=request,
        name="blog_liste.html",
        context={
            **baglam,
            "baslik": f"{etiket_adi} etiketli yazılar",
            "aciklama": f"“{etiket_adi}” konusunda yazılmış {toplam} yazı.",
            "yazilar": yazilar,
            "sayfa": sayfa,
            "toplam_sayfa": toplam_sayfa,
            "taban": f"/etiket/{etiket_slug}",
            "arama": None,
            "etiketler": None,
            "kirinti_ogeleri": kirinti(
                ("Anasayfa", f"{site}/"),
                ("Blog", f"{site}/blog"),
                (etiket_adi, f"{site}/etiket/{etiket_slug}"),
            ),
        },
    )


# ==================================================================
# Yazi detayi
# ==================================================================
@router.get("/blog/{yazi_slug}", response_class=HTMLResponse, summary="Yazı detayı")
@rate_limit(scope="public")
@cache_response(ttl=300, prefix="yazi")
@retry(attempts=2)
@timeit
@log
async def yazi_detay(
    request: Request, yazi_slug: str, arka_plan: BackgroundTasks
) -> HTMLResponse:
    """Tek bir yaziyi gosterir; taslaklar yalnizca oturum acikken gorunur."""
    baglam = await temel_baglam(request, aktif="blog")
    oturum_var = bool(request.cookies.get(settings.session_cookie_name))

    yazi = await repo.get_post_by_slug(yazi_slug, only_published=not oturum_var)
    if yazi is None:
        return _hata_sayfasi(
            request, baglam, 404, "Yazı bulunamadı",
            "Aradığınız yazı kaldırılmış veya adresi değişmiş olabilir.",
        )

    arka_plan.add_task(repo.increment_view_count, int(yazi["id"]))
    site = baglam["site_url"]

    return templates.TemplateResponse(
        request=request,
        name="blog_detay.html",
        context={
            **baglam,
            "yazi": yazi,
            "komsular": await repo.get_adjacent_posts(yazi["published_at"], int(yazi["id"])),
            "benzerler": await repo.related_posts(int(yazi["id"]), limit=3),
            "kelime_sayisi": len(plain_text(yazi["content_html"]).split()),
            "kirinti_ogeleri": kirinti(
                ("Anasayfa", f"{site}/"),
                ("Blog", f"{site}/blog"),
                (yazi["title"], f"{site}/blog/{yazi['slug']}"),
            ),
        },
    )


# ==================================================================
# Iletisim formu
# ==================================================================
async def _iletisim_baglami(request: Request) -> dict:
    """Iletisim sayfasinin hem GET hem POST'ta kullandigi ortak baglami kurar."""
    baglam = await temel_baglam(request, aktif="iletisim")
    sayfa = await repo.get_page("iletisim") or {
        "slug": "iletisim", "title": "İletişim", "content_html": "",
        "meta_description": None, "updated_at": datetime.now(UTC),
    }
    site = baglam["site_url"]
    return {
        **baglam,
        "sayfa": sayfa,
        "kirinti_ogeleri": kirinti(("Anasayfa", f"{site}/"), ("İletişim", f"{site}/iletisim")),
    }


# NOT: Bu sayfa bilerek `@cache_response` ALMAZ. Formda her render'da yeniden
# uretilen, zaman damgali bir bot-koruma token'i var; onbelleklenen HTML ayni
# token'i dakikalarca herkese dagitir ve "cok hizli gonderim" olcumu anlamsizlasir.
# Sayfanin geri kalani zaten tek bir hafif sorgudan ibaret.
@router.get("/iletisim", response_class=HTMLResponse, summary="İletişim sayfası")
@rate_limit(scope="public")
@retry(attempts=2)
@timeit
@log
async def iletisim_sayfasi(request: Request) -> HTMLResponse:
    """Iletisim sayfasini ve mesaj formunu gosterir."""
    ortak = await _iletisim_baglami(request)
    return templates.TemplateResponse(
        request=request, name="iletisim.html",
        context={**ortak, "durum": None, "eski": {}, "form_token": form_tokeni_uret()},
    )


@router.post("/iletisim", response_class=HTMLResponse, summary="İletişim formu gönderimi")
@rate_limit(requests=5, window_seconds=600, scope="iletisim")
@timeit
@log
async def iletisim_gonder(
    request: Request,
    arka_plan: BackgroundTasks,
    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),
    subject: str = Form(default=""),
    website: str = Form(default=""),
    form_token: str = Form(default=""),
) -> HTMLResponse:
    """Iletisim mesajini dogrular, kaydeder ve site sahibine e-posta ile bildirir."""
    ortak = {
        **await _iletisim_baglami(request),
        "eski": {"name": name, "email": email, "subject": subject, "message": message},
        # Hata durumunda form yeniden cizilir; taze token olmazsa kullanici
        # ikinci denemede de takilir.
        "form_token": form_tokeni_uret(),
    }

    # Bot tuzagi doluysa basarili gibi davran, kayit acma
    if website.strip():
        logger.info("Iletisim formunda bot tuzagi tetiklendi: ip=%s", client_ip(request))
        return templates.TemplateResponse(
            request=request, name="iletisim.html",
            context={**ortak, "durum": "basarili", "eski": {}},
        )

    # Zaman damgali token: cok hizli veya cok eski gonderimleri eler
    try:
        form_tokeni_dogrula(form_token)
    except FormTokenHatasi as exc:
        logger.info(
            "Iletisim formu token dogrulamasi basarisiz: ip=%s neden=%s",
            client_ip(request), exc.kayit_nedeni,
        )
        return templates.TemplateResponse(
            request=request, name="iletisim.html",
            context={**ortak, "durum": "hata", "hata_mesaji": exc.kullanici_mesaji},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        veri = ContactCreate(
            name=name, email=email, subject=subject or None, message=message, website=""
        )
    except ValidationError as exc:
        ilk = exc.errors()[0]
        return templates.TemplateResponse(
            request=request, name="iletisim.html",
            context={**ortak, "durum": "hata", "hata_mesaji": ilk.get("msg", "Geçersiz veri.")},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    mesaj_id = await repo.create_contact_message(
        name=veri.name,
        email=str(veri.email),
        subject=veri.subject,
        message=veri.message,
        ip=client_ip(request),
    )
    arka_plan.add_task(
        repo.write_audit,
        actor=str(veri.email), actor_type="visitor", action="create",
        entity="contact_message", entity_id=str(mesaj_id), ip=client_ip(request),
    )
    # SMTP bloklayici; ziyaretciyi bekletmemek icin arka planda gonderilir.
    # Mesaj zaten DB'ye yazildi — e-posta gitmese de kayip yok, panelden gorulur.
    arka_plan.add_task(
        iletisim_bildirimi_gonder,
        ad=veri.name, eposta=str(veri.email), konu=veri.subject,
        mesaj=veri.message, ip=client_ip(request), mesaj_id=mesaj_id,
    )

    return templates.TemplateResponse(
        request=request, name="iletisim.html",
        context={**ortak, "durum": "basarili", "eski": {}},
    )


# ==================================================================
# sitemap · robots
# ==================================================================
@router.get("/sitemap.xml", summary="Site haritası", include_in_schema=False)
@timeit
@log
async def sitemap(request: Request) -> Response:
    """Tum public URL'leri lastmod bilgisiyle listeler."""
    site = settings.site_url.rstrip("/")
    girdiler: list[tuple[str, datetime | None, str, str]] = [
        (f"{site}/", None, "weekly", "1.0"),
        (f"{site}/blog", None, "daily", "0.9"),
    ]

    for sayfa in await repo.list_pages():
        if sayfa["is_published"]:
            girdiler.append((f"{site}/{sayfa['slug']}", sayfa["updated_at"], "monthly", "0.7"))

    yazilar, _ = await repo.list_posts(page=1, per_page=50, status=PostStatus.PUBLISHED)
    for y in yazilar:
        girdiler.append((f"{site}/blog/{y['slug']}", y["updated_at"], "monthly", "0.8"))

    for etiket in await repo.list_tags(limit=100):
        girdiler.append((f"{site}/etiket/{etiket['slug']}", None, "weekly", "0.5"))

    satirlar = []
    for url, lastmod, freq, oncelik in girdiler:
        parca = [f"    <loc>{escape(url)}</loc>"]
        if lastmod:
            parca.append(f"    <lastmod>{lastmod.date().isoformat()}</lastmod>")
        parca.append(f"    <changefreq>{freq}</changefreq>")
        parca.append(f"    <priority>{oncelik}</priority>")
        satirlar.append("  <url>\n" + "\n".join(parca) + "\n  </url>")

    govde = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(satirlar)
        + "\n</urlset>\n"
    )
    return Response(content=govde, media_type="application/xml; charset=utf-8")


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots() -> PlainTextResponse:
    """Arama motoru tarama kurallarini dondurur."""
    site = settings.site_url.rstrip("/")
    return PlainTextResponse(
        f"""User-agent: *
Allow: /
Disallow: /panel
Disallow: /giris
Disallow: /api/

Sitemap: {site}/sitemap.xml
"""
    )


# ==================================================================
# Statik sayfalar — en sonda tanimlanir (catch-all)
# ==================================================================
@router.get("/{sayfa_slug}", response_class=HTMLResponse, summary="Statik sayfa")
@rate_limit(scope="public")
@cache_response(ttl=600, prefix="sayfa")
@retry(attempts=2)
@timeit
@log
async def statik_sayfa(request: Request, sayfa_slug: str) -> HTMLResponse:
    """Hakkimda / iletisim gibi statik sayfalari gosterir."""
    baglam = await temel_baglam(request, aktif=sayfa_slug)
    sayfa = await repo.get_page(sayfa_slug)
    if sayfa is None:
        return _hata_sayfasi(
            request, baglam, 404, "Sayfa bulunamadı",
            "Aradığınız sayfa taşınmış veya kaldırılmış olabilir.",
        )

    site = baglam["site_url"]
    ortak = {
        **baglam,
        "sayfa": sayfa,
        "kirinti_ogeleri": kirinti(
            ("Anasayfa", f"{site}/"), (sayfa["title"], f"{site}/{sayfa['slug']}")
        ),
    }
    # /iletisim artik kendi (onbelleklenmeyen) route'unda karsilanir — buraya dusmez.
    return templates.TemplateResponse(request=request, name="sayfa.html", context=ortak)
