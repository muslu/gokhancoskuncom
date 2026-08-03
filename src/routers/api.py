"""REST API (/api/v1) — MCP sunucusu ve dis istemciler icin.

Kimlik dogrulama: `Authorization: Bearer <token>`. Tokenlar panelden uretilir,
DB'de yalnizca SHA-256 ozeti saklanir.
"""

import math
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from src.auth import require_api_token, require_scope
from src.cache import invalidate_public_cache
from src.decorators import cache_response, client_ip, log, rate_limit, retry, timeit
from src.models import repository as repo
from src.models.schemas import (
    PageUpdate,
    PostCreate,
    PostDetail,
    PostListResponse,
    PostStatus,
    PostSummary,
    PostUpdate,
    ProfilePublic,
    ProfileUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["API"])


def _yazi_yaniti(satir: dict[str, Any]) -> dict[str, Any]:
    """DB satirini API detay modeline cevirir."""
    return PostDetail.model_validate(satir).model_dump(mode="json")


# ==================================================================
# Yazilar — okuma
# ==================================================================
@router.get("/yazilar", response_model=PostListResponse, summary="Yazıları listele")
@rate_limit(scope="api")
@cache_response(ttl=60, prefix="api-yazilar", vary_cookie=True)
@retry(attempts=2)
@timeit
@log
async def yazilari_listele(
    request: Request,
    sayfa: int = Query(default=1, ge=1, le=1000, description="Sayfa numarası"),
    adet: int = Query(default=20, ge=1, le=50, description="Sayfa başına kayıt"),
    durum: str | None = Query(default=None, description="draft | published (boş: tümü)"),
    etiket: str | None = Query(default=None, max_length=80, description="Etiket slug'ı"),
    ara: str | None = Query(default=None, max_length=100, description="Arama terimi"),
    token: dict[str, Any] = Depends(require_scope("posts:read")),
) -> dict[str, Any]:
    """Yazilari sayfalayarak dondurur; taslaklar dahil edilebilir."""
    secili = PostStatus(durum) if durum in ("draft", "published") else None
    satirlar, toplam = await repo.list_posts(
        page=sayfa, per_page=adet, status=secili, tag=etiket, search=ara
    )
    return PostListResponse(
        items=[PostSummary.model_validate(s) for s in satirlar],
        total=toplam,
        page=sayfa,
        per_page=adet,
        pages=max(1, math.ceil(toplam / adet)),
    ).model_dump(mode="json")


@router.get("/yazilar/{yazi_slug}", response_model=PostDetail, summary="Yazı detayı")
@rate_limit(scope="api")
@cache_response(ttl=60, prefix="api-yazi", vary_cookie=True)
@retry(attempts=2)
@timeit
@log
async def yazi_getir(
    request: Request,
    yazi_slug: str,
    token: dict[str, Any] = Depends(require_scope("posts:read")),
) -> dict[str, Any]:
    """Slug'a gore tek yaziyi dondurur (taslaklar dahil)."""
    yazi = await repo.get_post_by_slug(yazi_slug, only_published=False)
    if yazi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Yazı bulunamadı: {yazi_slug}"
        )
    return _yazi_yaniti(yazi)


# ==================================================================
# Yazilar — yazma
# ==================================================================
@router.post(
    "/yazilar",
    response_model=PostDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni yazı oluştur",
)
@rate_limit(requests=60, window_seconds=60, scope="api-yazma")
@retry(attempts=2)
@timeit
@log
async def yazi_olustur(
    request: Request,
    payload: PostCreate,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("posts:write")),
) -> dict[str, Any]:
    """Yeni blog yazisi olusturur ve olusan kaydi dondurur."""
    yazi = await repo.create_post(payload, author_id=int(token["owner_id"]))
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="create", entity="post", entity_id=yazi["slug"],
        detail={"status": yazi["status"], "title": yazi["title"]}, ip=client_ip(request),
    )
    return _yazi_yaniti(yazi)


@router.patch("/yazilar/{yazi_slug}", response_model=PostDetail, summary="Yazıyı güncelle")
@rate_limit(requests=60, window_seconds=60, scope="api-yazma")
@retry(attempts=2)
@timeit
@log
async def yazi_guncelle(
    request: Request,
    yazi_slug: str,
    payload: PostUpdate,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("posts:write")),
) -> dict[str, Any]:
    """Gonderilen alanlari gunceller (kismi guncelleme)."""
    yazi = await repo.update_post(yazi_slug, payload)
    if yazi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Yazı bulunamadı: {yazi_slug}"
        )
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="update", entity="post", entity_id=yazi_slug,
        detail=payload.model_dump(exclude_unset=True, mode="json"), ip=client_ip(request),
    )
    return _yazi_yaniti(yazi)


@router.post("/yazilar/{yazi_slug}/yayinla", response_model=PostDetail, summary="Yazıyı yayınla")
@rate_limit(requests=60, window_seconds=60, scope="api-yazma")
@timeit
@log
async def yazi_yayinla(
    request: Request,
    yazi_slug: str,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("posts:write")),
) -> dict[str, Any]:
    """Taslak yaziyi yayina alir."""
    yazi = await repo.set_post_status(yazi_slug, PostStatus.PUBLISHED)
    if yazi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Yazı bulunamadı: {yazi_slug}"
        )
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="publish", entity="post", entity_id=yazi_slug, ip=client_ip(request),
    )
    return _yazi_yaniti(yazi)


@router.post(
    "/yazilar/{yazi_slug}/taslaga-al", response_model=PostDetail, summary="Yazıyı taslağa al"
)
@rate_limit(requests=60, window_seconds=60, scope="api-yazma")
@timeit
@log
async def yazi_taslaga_al(
    request: Request,
    yazi_slug: str,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("posts:write")),
) -> dict[str, Any]:
    """Yayindaki yaziyi taslaga cevirir."""
    yazi = await repo.set_post_status(yazi_slug, PostStatus.DRAFT)
    if yazi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Yazı bulunamadı: {yazi_slug}"
        )
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="unpublish", entity="post", entity_id=yazi_slug, ip=client_ip(request),
    )
    return _yazi_yaniti(yazi)


@router.delete(
    "/yazilar/{yazi_slug}", status_code=status.HTTP_200_OK, summary="Yazıyı sil"
)
@rate_limit(requests=30, window_seconds=60, scope="api-yazma")
@timeit
@log
async def yazi_sil(
    request: Request,
    yazi_slug: str,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("posts:write")),
) -> dict[str, Any]:
    """Yaziyi kalici olarak siler."""
    if not await repo.delete_post(yazi_slug):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Yazı bulunamadı: {yazi_slug}"
        )
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="delete", entity="post", entity_id=yazi_slug, ip=client_ip(request),
    )
    return {"silindi": True, "slug": yazi_slug}


# ==================================================================
# Etiketler
# ==================================================================
@router.get("/etiketler", summary="Etiketleri listele")
@rate_limit(scope="api")
@cache_response(ttl=300, prefix="api-etiket", vary_cookie=True)
@timeit
@log
async def etiketleri_listele(
    request: Request,
    token: dict[str, Any] = Depends(require_scope("posts:read")),
) -> list[dict[str, Any]]:
    """Yayindaki yazi sayisiyla birlikte etiketleri dondurur."""
    return [
        {"slug": e["slug"], "name": e["name"], "post_count": int(e["post_count"])}
        for e in await repo.list_tags(limit=200)
    ]


# ==================================================================
# Sayfalar
# ==================================================================
@router.get("/sayfalar", summary="Sayfaları listele")
@rate_limit(scope="api")
@cache_response(ttl=300, prefix="api-sayfalar", vary_cookie=True)
@timeit
@log
async def sayfalari_listele(
    request: Request,
    token: dict[str, Any] = Depends(require_scope("posts:read")),
) -> list[dict[str, Any]]:
    """Duzenlenebilir statik sayfalari dondurur."""
    return [
        {
            "slug": s["slug"],
            "title": s["title"],
            "content_md": s["content_md"],
            "meta_description": s["meta_description"],
            "is_published": s["is_published"],
            "show_in_menu": s["show_in_menu"],
            "sort_order": s["sort_order"],
            "updated_at": s["updated_at"].isoformat(),
        }
        for s in await repo.list_pages()
    ]


@router.patch("/sayfalar/{sayfa_slug}", summary="Sayfayı güncelle")
@rate_limit(requests=30, window_seconds=60, scope="api-yazma")
@timeit
@log
async def sayfa_guncelle(
    request: Request,
    sayfa_slug: str,
    payload: PageUpdate,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("pages:write")),
) -> dict[str, Any]:
    """Statik sayfanin icerigini gunceller."""
    sonuc = await repo.update_page(sayfa_slug, payload.model_dump(exclude_unset=True))
    if sonuc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Sayfa bulunamadı: {sayfa_slug}"
        )
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="update", entity="page", entity_id=sayfa_slug, ip=client_ip(request),
    )
    return {
        "slug": sonuc["slug"],
        "title": sonuc["title"],
        "content_md": sonuc["content_md"],
        "is_published": sonuc["is_published"],
        "updated_at": sonuc["updated_at"].isoformat(),
    }


# ==================================================================
# Profil
# ==================================================================
@router.get("/profil", response_model=ProfilePublic, summary="Kişisel bilgileri getir")
@rate_limit(scope="api")
@cache_response(ttl=300, prefix="api-profil", vary_cookie=True)
@timeit
@log
async def profil_getir(
    request: Request,
    token: dict[str, Any] = Depends(require_scope("posts:read")),
) -> dict[str, Any]:
    """Kisisel bilgileri dondurur."""
    return ProfilePublic.model_validate(await repo.get_profile()).model_dump(mode="json")


@router.patch("/profil", response_model=ProfilePublic, summary="Kişisel bilgileri güncelle")
@rate_limit(requests=30, window_seconds=60, scope="api-yazma")
@timeit
@log
async def profil_guncelle(
    request: Request,
    payload: ProfileUpdate,
    arka_plan: BackgroundTasks,
    token: dict[str, Any] = Depends(require_scope("profile:write")),
) -> dict[str, Any]:
    """Kisisel bilgileri gunceller."""
    sonuc = await repo.update_profile(payload)
    arka_plan.add_task(invalidate_public_cache)
    arka_plan.add_task(
        repo.write_audit,
        actor=f"{token['username']}/{token['name']}", actor_type="api_token",
        action="update", entity="profile", entity_id="1", ip=client_ip(request),
    )
    return ProfilePublic.model_validate(sonuc).model_dump(mode="json")


# ==================================================================
# Yardimci
# ==================================================================
@router.get("/kimlik", summary="Token bilgisini doğrula")
@rate_limit(scope="api")
@timeit
@log
async def kimlik(
    request: Request, token: dict[str, Any] = Depends(require_api_token)
) -> dict[str, Any]:
    """Token'in gecerli oldugunu ve yetkilerini dondurur (MCP baglanti testi)."""
    return {
        "gecerli": True,
        "token_adi": token["name"],
        "kullanici": token["username"],
        "rol": token["role"],
        "yetkiler": [s.strip() for s in str(token["scopes"]).split(",")],
    }
