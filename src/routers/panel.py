"""Yonetim paneli: giris, yazi/sayfa yonetimi, profil, mesajlar, API tokenlari."""

import math
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth import authenticate_cookie, create_access_token
from src.cache import invalidate_public_cache
from src.colorlogger import logger
from src.config import settings
from src.crypto import generate_api_token, verify_password
from src.decorators import client_ip, log, rate_limit, timeit
from src.models import repository as repo
from src.models.schemas import (
    PageUpdate,
    PostCreate,
    PostStatus,
    PostUpdate,
    ProfileUpdate,
    TokenCreate,
)
from src.templating import ASSET_VERSION, templates

router = APIRouter(tags=["Panel"], include_in_schema=False)

YAZI_SAYFA_BOYUTU = 20

SOSYAL_ALANLAR = [
    ("github", "GitHub"),
    ("linkedin", "LinkedIn"),
    ("x", "X (Twitter)"),
    ("instagram", "Instagram"),
    ("youtube", "YouTube"),
    ("mastodon", "Mastodon"),
    ("website", "Web sitesi"),
]

KAPSAMLAR = [
    ("posts:read", "Yazıları okuma"),
    ("posts:write", "Yazı oluşturma ve düzenleme"),
    ("pages:write", "Sayfaları düzenleme"),
    ("profile:write", "Kişisel bilgileri düzenleme"),
]


async def _panel_baglam(request: Request, kullanici: dict[str, Any], aktif: str) -> dict[str, Any]:
    """Panel sablonlari icin ortak baglam."""
    istatistik = await repo.post_stats()
    return {
        "request": request,
        "kullanici": kullanici,
        "profil": await repo.get_profile(),
        "site_url": settings.site_url.rstrip("/"),
        "panel_url": settings.panel_url.rstrip("/"),
        "asset_version": ASSET_VERSION,
        "aktif": aktif,
        "okunmamis": istatistik["okunmamis_mesaj"],
        "mesaj": request.query_params.get("mesaj"),
        "hata": request.query_params.get("hata"),
    }


def _yonlendir(yol: str, mesaj: str | None = None, hata: str | None = None) -> RedirectResponse:
    """POST sonrasi PRG (Post/Redirect/Get) yonlendirmesi uretir."""
    from urllib.parse import urlencode

    sorgu = {k: v for k, v in (("mesaj", mesaj), ("hata", hata)) if v}
    hedef = f"{yol}?{urlencode(sorgu)}" if sorgu else yol
    return RedirectResponse(url=hedef, status_code=status.HTTP_303_SEE_OTHER)


def _etiketleri_ayikla(ham: str) -> list[str]:
    """Virgulle ayrilmis etiket dizesini listeye cevirir."""
    return [p.strip() for p in (ham or "").split(",") if p.strip()][:12]


# ==================================================================
# Giris / cikis
# ==================================================================
@router.get("/giris", response_class=HTMLResponse)
@rate_limit(scope="giris-sayfa")
@timeit
@log
async def giris_formu(request: Request) -> HTMLResponse:
    """Panel giris formunu gosterir; oturum aciksa panele yonlendirir."""
    if await authenticate_cookie(request) is not None:
        return RedirectResponse(url="/panel", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="panel/giris.html",
        context={
            "request": request,
            "profil": await repo.get_profile(),
            "asset_version": ASSET_VERSION,
            "hata": None,
            "eski_kullanici": None,
        },
    )


@router.post("/giris", response_class=HTMLResponse)
@rate_limit(
    requests=settings.login_rate_limit_requests,
    window_seconds=settings.login_rate_limit_window_seconds,
    scope="giris",
)
@timeit
@log
async def giris_yap(
    request: Request,
    arka_plan: BackgroundTasks,
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    """Kullanici adi + parola dogrular ve oturum cerezi kurar."""
    ip = client_ip(request)
    kullanici = await repo.authenticate_user(username.strip(), password)

    if kullanici is None:
        logger.warning("Basarisiz panel girisi: kullanici=%s ip=%s", username, ip)
        arka_plan.add_task(
            repo.write_audit,
            actor=username[:100], action="login_failed", entity="user", ip=ip,
        )
        return templates.TemplateResponse(
            request=request,
            name="panel/giris.html",
            context={
                "request": request,
                "profil": await repo.get_profile(),
                "asset_version": ASSET_VERSION,
                "hata": "Kullanıcı adı veya parola hatalı.",
                "eski_kullanici": username,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    yanit = RedirectResponse(url="/panel", status_code=status.HTTP_303_SEE_OTHER)
    yanit.set_cookie(
        key=settings.session_cookie_name,
        value=create_access_token(kullanici),
        max_age=settings.token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="login", entity="user",
        entity_id=str(kullanici["id"]), ip=ip,
    )
    logger.info("Panel girisi: %s (ip=%s)", kullanici["username"], ip)
    return yanit


@router.post("/panel/cikis")
@timeit
@log
async def cikis_yap(request: Request) -> RedirectResponse:
    """Oturum cerezini siler."""
    yanit = RedirectResponse(url="/giris", status_code=status.HTTP_303_SEE_OTHER)
    yanit.delete_cookie(settings.session_cookie_name, path="/")
    return yanit


# ==================================================================
# Gosterge paneli
# ==================================================================
@router.get("/panel", response_class=HTMLResponse)
@timeit
@log
async def gosterge(request: Request) -> HTMLResponse:
    """Ozet sayilar ve son yazilari gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    yazilar, _ = await repo.list_posts(page=1, per_page=8, status=None)
    return templates.TemplateResponse(
        request=request,
        name="panel/gosterge.html",
        context={
            **await _panel_baglam(request, kullanici, "gosterge"),
            "istatistik": await repo.post_stats(),
            "yazilar": yazilar,
        },
    )


# ==================================================================
# Yazi yonetimi
# ==================================================================
@router.get("/panel/yazilar", response_class=HTMLResponse)
@timeit
@log
async def yazi_listesi(
    request: Request,
    sayfa: int = Query(default=1, ge=1, le=1000),
    ara: str | None = Query(default=None, max_length=100),
    durum: str | None = Query(default=None, max_length=20),
) -> HTMLResponse:
    """Tum yazilari filtreleyerek listeler."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    secili_durum = PostStatus(durum) if durum in ("draft", "published") else None
    yazilar, toplam = await repo.list_posts(
        page=sayfa, per_page=YAZI_SAYFA_BOYUTU, status=secili_durum, search=ara
    )
    return templates.TemplateResponse(
        request=request,
        name="panel/yazilar.html",
        context={
            **await _panel_baglam(request, kullanici, "yazilar"),
            "yazilar": yazilar,
            "sayfa": sayfa,
            "toplam_sayfa": max(1, math.ceil(toplam / YAZI_SAYFA_BOYUTU)),
            "arama": ara,
            "durum": durum,
        },
    )


@router.get("/panel/yazilar/yeni", response_class=HTMLResponse)
@timeit
@log
async def yeni_yazi_formu(request: Request) -> HTMLResponse:
    """Bos yazi formunu gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/yazi_form.html",
        context={
            **await _panel_baglam(request, kullanici, "yeni"),
            "yeni": True,
            "yazi": {"status": "draft", "tags": []},
        },
    )


@router.post("/panel/yazilar/yeni")
@timeit
@log
async def yeni_yazi_kaydet(
    request: Request,
    arka_plan: BackgroundTasks,
    title: str = Form(...),
    content_md: str = Form(...),
    summary: str = Form(default=""),
    tags: str = Form(default=""),
    cover_image: str = Form(default=""),
    meta_description: str = Form(default=""),
    status_: str = Form(default="draft", alias="status"),
    is_featured: str = Form(default=""),
) -> RedirectResponse:
    """Yeni yazi olusturur."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    try:
        veri = PostCreate(
            title=title.strip(),
            content_md=content_md,
            summary=summary.strip() or None,
            tags=_etiketleri_ayikla(tags),
            cover_image=cover_image.strip() or None,
            meta_description=meta_description.strip() or None,
            status=PostStatus(status_) if status_ in ("draft", "published") else PostStatus.DRAFT,
            is_featured=bool(is_featured),
        )
    except ValueError as exc:
        return _yonlendir("/panel/yazilar/yeni", hata=f"Geçersiz veri: {exc}")

    yazi = await repo.create_post(veri, author_id=int(kullanici["id"]))
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="create", entity="post",
        entity_id=yazi["slug"], detail={"status": yazi["status"]}, ip=client_ip(request),
    )
    return _yonlendir(f"/panel/yazilar/{yazi['slug']}", mesaj="Yazı oluşturuldu.")


@router.get("/panel/yazilar/{yazi_slug}", response_class=HTMLResponse)
@timeit
@log
async def yazi_duzenle_formu(request: Request, yazi_slug: str) -> HTMLResponse:
    """Mevcut yazinin duzenleme formunu gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    yazi = await repo.get_post_by_slug(yazi_slug, only_published=False)
    if yazi is None:
        return _yonlendir("/panel/yazilar", hata="Yazı bulunamadı.")

    return templates.TemplateResponse(
        request=request,
        name="panel/yazi_form.html",
        context={
            **await _panel_baglam(request, kullanici, "yazilar"),
            "yeni": False,
            "yazi": yazi,
        },
    )


@router.post("/panel/yazilar/{yazi_slug}")
@timeit
@log
async def yazi_guncelle(
    request: Request,
    yazi_slug: str,
    arka_plan: BackgroundTasks,
    title: str = Form(...),
    content_md: str = Form(...),
    summary: str = Form(default=""),
    tags: str = Form(default=""),
    cover_image: str = Form(default=""),
    meta_description: str = Form(default=""),
    status_: str = Form(default="draft", alias="status"),
    is_featured: str = Form(default=""),
) -> RedirectResponse:
    """Yaziyi gunceller."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    try:
        veri = PostUpdate(
            title=title.strip(),
            content_md=content_md,
            summary=summary.strip() or None,
            tags=_etiketleri_ayikla(tags),
            cover_image=cover_image.strip() or None,
            meta_description=meta_description.strip() or None,
            status=PostStatus(status_) if status_ in ("draft", "published") else PostStatus.DRAFT,
            is_featured=bool(is_featured),
        )
    except ValueError as exc:
        return _yonlendir(f"/panel/yazilar/{yazi_slug}", hata=f"Geçersiz veri: {exc}")

    yazi = await repo.update_post(yazi_slug, veri)
    if yazi is None:
        return _yonlendir("/panel/yazilar", hata="Yazı bulunamadı.")

    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="update", entity="post",
        entity_id=yazi_slug, ip=client_ip(request),
    )
    return _yonlendir(f"/panel/yazilar/{yazi['slug']}", mesaj="Değişiklikler kaydedildi.")


@router.post("/panel/yazilar/{yazi_slug}/durum")
@timeit
@log
async def yazi_durum_degistir(
    request: Request,
    yazi_slug: str,
    arka_plan: BackgroundTasks,
    status_: str = Form(default="draft", alias="status"),
) -> RedirectResponse:
    """Yaziyi yayina alir veya taslaga cevirir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    yeni_durum = PostStatus(status_) if status_ in ("draft", "published") else PostStatus.DRAFT
    yazi = await repo.set_post_status(yazi_slug, yeni_durum)
    if yazi is None:
        return _yonlendir("/panel/yazilar", hata="Yazı bulunamadı.")

    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="status_change", entity="post",
        entity_id=yazi_slug, detail={"status": yeni_durum.value}, ip=client_ip(request),
    )
    etiket = "yayınlandı" if yeni_durum == PostStatus.PUBLISHED else "taslağa alındı"
    return _yonlendir("/panel/yazilar", mesaj=f"“{yazi['title']}” {etiket}.")


@router.post("/panel/yazilar/{yazi_slug}/sil")
@timeit
@log
async def yazi_sil(
    request: Request, yazi_slug: str, arka_plan: BackgroundTasks
) -> RedirectResponse:
    """Yaziyi kalici olarak siler."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    if not await repo.delete_post(yazi_slug):
        return _yonlendir("/panel/yazilar", hata="Yazı bulunamadı.")

    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="delete", entity="post",
        entity_id=yazi_slug, ip=client_ip(request),
    )
    return _yonlendir("/panel/yazilar", mesaj="Yazı silindi.")


# ==================================================================
# Sayfa yonetimi
# ==================================================================
@router.get("/panel/sayfalar", response_class=HTMLResponse)
@timeit
@log
async def sayfa_listesi(request: Request) -> HTMLResponse:
    """Duzenlenebilir statik sayfalari listeler."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/sayfalar.html",
        context={
            **await _panel_baglam(request, kullanici, "sayfalar"),
            "sayfalar": await repo.list_pages(),
        },
    )


@router.post("/panel/sayfalar/{sayfa_slug}")
@timeit
@log
async def sayfa_guncelle(
    request: Request,
    sayfa_slug: str,
    arka_plan: BackgroundTasks,
    title: str = Form(...),
    content_md: str = Form(default=""),
    meta_description: str = Form(default=""),
    sort_order: int = Form(default=0),
    is_published: str = Form(default=""),
    show_in_menu: str = Form(default=""),
) -> RedirectResponse:
    """Statik sayfayi gunceller."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    try:
        veri = PageUpdate(
            title=title.strip(),
            content_md=content_md,
            meta_description=meta_description.strip() or None,
            sort_order=max(0, min(999, sort_order)),
            is_published=bool(is_published),
            show_in_menu=bool(show_in_menu),
        )
    except ValueError as exc:
        return _yonlendir("/panel/sayfalar", hata=f"Geçersiz veri: {exc}")

    sonuc = await repo.update_page(sayfa_slug, veri.model_dump(exclude_unset=True))
    if sonuc is None:
        return _yonlendir("/panel/sayfalar", hata="Sayfa bulunamadı.")

    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="update", entity="page",
        entity_id=sayfa_slug, ip=client_ip(request),
    )
    return _yonlendir("/panel/sayfalar", mesaj=f"“{sonuc['title']}” kaydedildi.")


# ==================================================================
# Profil
# ==================================================================
@router.get("/panel/profil", response_class=HTMLResponse)
@timeit
@log
async def profil_formu(request: Request) -> HTMLResponse:
    """Kisisel bilgi duzenleme formunu gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/profil.html",
        context={
            **await _panel_baglam(request, kullanici, "profil"),
            "sosyal_alanlar": SOSYAL_ALANLAR,
        },
    )


@router.post("/panel/profil")
@timeit
@log
async def profil_kaydet(request: Request, arka_plan: BackgroundTasks) -> RedirectResponse:
    """Kisisel bilgileri gunceller."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    form = await request.form()
    sosyaller = {
        anahtar: str(form.get(f"sosyal_{anahtar}", "")).strip()
        for anahtar, _ in SOSYAL_ALANLAR
        if str(form.get(f"sosyal_{anahtar}", "")).strip()
    }

    try:
        veri = ProfileUpdate(
            full_name=str(form.get("full_name", "")).strip() or None,
            title=str(form.get("title", "")).strip(),
            tagline=str(form.get("tagline", "")).strip(),
            bio_md=str(form.get("bio_md", "")),
            avatar_url=str(form.get("avatar_url", "")).strip() or None,
            email=str(form.get("email", "")).strip() or None,
            phone=str(form.get("phone", "")).strip() or None,
            location=str(form.get("location", "")).strip() or None,
            socials=sosyaller,
        )
    except ValueError as exc:
        return _yonlendir("/panel/profil", hata=f"Geçersiz veri: {exc}")

    await repo.update_profile(veri)
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="update", entity="profile",
        entity_id="1", ip=client_ip(request),
    )
    return _yonlendir("/panel/profil", mesaj="Kişisel bilgiler güncellendi.")


@router.post("/panel/parola")
@rate_limit(requests=5, window_seconds=600, scope="parola")
@timeit
@log
async def parola_degistir(
    request: Request,
    arka_plan: BackgroundTasks,
    mevcut_parola: str = Form(...),
    yeni_parola: str = Form(...),
    yeni_parola_tekrar: str = Form(...),
) -> RedirectResponse:
    """Oturum sahibinin parolasini degistirir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    if yeni_parola != yeni_parola_tekrar:
        return _yonlendir("/panel/profil", hata="Yeni parolalar birbiriyle eşleşmiyor.")
    if len(yeni_parola) < 8:
        return _yonlendir("/panel/profil", hata="Yeni parola en az 8 karakter olmalı.")

    tam = await repo.get_user_by_username(kullanici["username"])
    if tam is None or not verify_password(mevcut_parola, tam["password_enc"]):
        logger.warning("Hatali mevcut parola: %s", kullanici["username"])
        return _yonlendir("/panel/profil", hata="Mevcut parola hatalı.")

    await repo.change_password(int(kullanici["id"]), yeni_parola)
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="password_change", entity="user",
        entity_id=str(kullanici["id"]), ip=client_ip(request),
    )
    return _yonlendir("/panel/profil", mesaj="Parolanız değiştirildi.")


# ==================================================================
# Mesajlar
# ==================================================================
@router.get("/panel/mesajlar", response_class=HTMLResponse)
@timeit
@log
async def mesaj_listesi(request: Request) -> HTMLResponse:
    """Iletisim formu mesajlarini listeler."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/mesajlar.html",
        context={
            **await _panel_baglam(request, kullanici, "mesajlar"),
            "mesajlar": await repo.list_contact_messages(limit=100),
        },
    )


@router.post("/panel/mesajlar/{mesaj_id}/okundu")
@timeit
@log
async def mesaj_okundu(request: Request, mesaj_id: int) -> RedirectResponse:
    """Mesaji okundu olarak isaretler."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    await repo.mark_message_read(mesaj_id)
    return _yonlendir("/panel/mesajlar", mesaj="Mesaj okundu olarak işaretlendi.")


# ==================================================================
# API tokenlari
# ==================================================================
@router.get("/panel/tokenlar", response_class=HTMLResponse)
@timeit
@log
async def token_listesi(request: Request) -> HTMLResponse:
    """API tokenlarini listeler ve uretim formunu gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/tokenlar.html",
        context={
            **await _panel_baglam(request, kullanici, "tokenlar"),
            "tokenlar": await repo.list_api_tokens(),
            "kapsamlar": KAPSAMLAR,
            # Ham token yalnizca uretildigi istekte gosterilir, DB'de saklanmaz
            "yeni_token": request.query_params.get("token"),
        },
    )


@router.post("/panel/tokenlar")
@timeit
@log
async def token_uret(request: Request, arka_plan: BackgroundTasks) -> RedirectResponse:
    """Yeni API token uretir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    form = await request.form()
    sure_ham = str(form.get("expires_days", "")).strip()
    try:
        veri = TokenCreate(
            name=str(form.get("name", "")).strip(),
            scopes=[str(s) for s in form.getlist("scopes")],
            expires_days=int(sure_ham) if sure_ham.isdigit() else None,
        )
    except ValueError as exc:
        return _yonlendir("/panel/tokenlar", hata=f"Geçersiz veri: {exc}")

    ham_token = generate_api_token()
    await repo.create_api_token(
        name=veri.name,
        scopes=veri.scopes,
        owner_id=int(kullanici["id"]),
        expires_days=veri.expires_days,
        raw_token=ham_token,
    )
    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="create", entity="api_token",
        entity_id=veri.name, detail={"scopes": veri.scopes}, ip=client_ip(request),
    )
    from urllib.parse import urlencode

    return RedirectResponse(
        url=f"/panel/tokenlar?{urlencode({'token': ham_token})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/panel/tokenlar/{token_id}/iptal")
@timeit
@log
async def token_iptal(
    request: Request, token_id: int, arka_plan: BackgroundTasks
) -> RedirectResponse:
    """Token'i pasifize eder."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")

    if not await repo.revoke_api_token(token_id):
        return _yonlendir("/panel/tokenlar", hata="Token bulunamadı.")

    arka_plan.add_task(
        repo.write_audit,
        actor=kullanici["username"], action="revoke", entity="api_token",
        entity_id=str(token_id), ip=client_ip(request),
    )
    return _yonlendir("/panel/tokenlar", mesaj="Token iptal edildi.")


# ==================================================================
# Denetim kaydi
# ==================================================================
@router.get("/panel/kayitlar", response_class=HTMLResponse)
@timeit
@log
async def denetim_kayitlari(request: Request) -> HTMLResponse:
    """Son denetim kayitlarini gosterir."""
    kullanici = await authenticate_cookie(request)
    if kullanici is None:
        return _yonlendir("/giris")
    return templates.TemplateResponse(
        request=request,
        name="panel/kayitlar.html",
        context={
            **await _panel_baglam(request, kullanici, "kayitlar"),
            "kayitlar": await repo.list_audit(limit=100),
        },
    )
