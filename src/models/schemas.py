"""Pydantic modelleri — kullanicidan gelen her veri burada dogrulanir.

Ham string kabul edilmez; enum alanlari whitelist ile sinirlanir.
"""

import re
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{2,50}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PostStatus(str, Enum):
    """Yazi durumu whitelist'i."""

    DRAFT = "draft"
    PUBLISHED = "published"


class UserRole(str, Enum):
    """Kullanici rolu whitelist'i."""

    ADMIN = "admin"
    EDITOR = "editor"


# ------------------------------------------------------------------
# Kimlik dogrulama
# ------------------------------------------------------------------
class LoginRequest(BaseModel):
    """Panel giris istegi."""

    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=200)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        """Kullanici adini regex ile dogrular."""
        if not USERNAME_RE.match(value):
            raise ValueError("Kullanıcı adı yalnızca harf, rakam, '_', '.', '-' içerebilir")
        return value


class UserPublic(BaseModel):
    """Panelde gosterilen kullanici bilgisi (parola icermez)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str | None = None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None = None


# ------------------------------------------------------------------
# Blog yazilari
# ------------------------------------------------------------------
class PostCreate(BaseModel):
    """Yeni blog yazisi olusturma istegi (panel + MCP ortak)."""

    title: str = Field(min_length=3, max_length=220)
    content_md: str = Field(min_length=1)
    summary: str | None = Field(default=None, max_length=500)
    slug: str | None = Field(default=None, max_length=220)
    tags: list[str] = Field(default_factory=list, max_length=12)
    cover_image: str | None = Field(default=None, max_length=500)
    meta_description: str | None = Field(default=None, max_length=300)
    status: PostStatus = PostStatus.DRAFT
    is_featured: bool = False
    published_at: datetime | None = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        """Verilmisse slug formatini dogrular."""
        if value is None:
            return None
        value = value.strip().lower()
        if not SLUG_RE.match(value):
            raise ValueError("Slug yalnızca küçük harf, rakam ve tire içerebilir")
        return value

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        """Bos etiketleri atar, uzunlugu sinirlar, tekrarlari kaldirir."""
        seen: list[str] = []
        for tag in value:
            cleaned = tag.strip()[:80]
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen


class PostUpdate(BaseModel):
    """Yazi guncelleme — yalnizca gonderilen alanlar degistirilir."""

    title: str | None = Field(default=None, min_length=3, max_length=220)
    content_md: str | None = Field(default=None, min_length=1)
    summary: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=12)
    cover_image: str | None = Field(default=None, max_length=500)
    meta_description: str | None = Field(default=None, max_length=300)
    status: PostStatus | None = None
    is_featured: bool | None = None
    published_at: datetime | None = None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str] | None) -> list[str] | None:
        """Etiketleri temizler (None ise dokunulmaz)."""
        if value is None:
            return None
        seen: list[str] = []
        for tag in value:
            cleaned = tag.strip()[:80]
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen


class PostSummary(BaseModel):
    """Liste gorunumunde donen ozet yazi modeli."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    summary: str | None = None
    cover_image: str | None = None
    status: PostStatus
    is_featured: bool
    reading_minutes: int
    view_count: int
    published_at: datetime | None = None
    updated_at: datetime
    tags: list[str] = Field(default_factory=list)


class PostDetail(PostSummary):
    """Detay gorunumu — Markdown ve HTML govde dahil."""

    content_md: str
    content_html: str
    meta_description: str | None = None
    author_name: str | None = None
    created_at: datetime


class PostListResponse(BaseModel):
    """Sayfalanmis yazi listesi yaniti."""

    items: list[PostSummary]
    total: int
    page: int
    per_page: int
    pages: int


# ------------------------------------------------------------------
# Sayfalar ve profil
# ------------------------------------------------------------------
class PageUpdate(BaseModel):
    """Statik sayfa guncelleme istegi."""

    title: str | None = Field(default=None, min_length=2, max_length=200)
    content_md: str | None = None
    meta_description: str | None = Field(default=None, max_length=300)
    is_published: bool | None = None
    show_in_menu: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class PagePublic(BaseModel):
    """Public sayfa modeli."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    content_md: str
    content_html: str
    meta_description: str | None = None
    is_published: bool
    show_in_menu: bool
    sort_order: int
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Kisisel bilgi guncelleme istegi."""

    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    title: str | None = Field(default=None, max_length=200)
    tagline: str | None = Field(default=None, max_length=300)
    bio_md: str | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=150)
    socials: dict[str, str] | None = None

    @field_validator("socials")
    @classmethod
    def _validate_socials(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Sosyal medya anahtarlarini whitelist ile sinirlar."""
        if value is None:
            return None
        allowed = {"github", "linkedin", "x", "twitter", "instagram", "youtube", "website", "mastodon"}
        return {k: v[:300] for k, v in value.items() if k in allowed and v}


class ProfilePublic(BaseModel):
    """Public profil modeli."""

    model_config = ConfigDict(from_attributes=True)

    full_name: str
    title: str
    tagline: str
    bio_md: str
    bio_html: str
    avatar_url: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    socials: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime


# ------------------------------------------------------------------
# Iletisim
# ------------------------------------------------------------------
class ContactCreate(BaseModel):
    """Iletisim formu gonderimi."""

    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=5000)
    # Bot tuzagi: gercek kullanicida bos kalir
    website: str = Field(default="", max_length=100)


# ------------------------------------------------------------------
# API tokenlari
# ------------------------------------------------------------------
class TokenCreate(BaseModel):
    """Yeni API token uretme istegi."""

    name: str = Field(min_length=2, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["posts:read", "posts:write"])
    expires_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: list[str]) -> list[str]:
        """Kapsamlari whitelist ile dogrular."""
        allowed = {"posts:read", "posts:write", "pages:write", "profile:write"}
        cleaned = [s for s in value if s in allowed]
        if not cleaned:
            raise ValueError(f"Geçerli kapsam verilmedi. İzin verilenler: {sorted(allowed)}")
        return cleaned


class TokenPublic(BaseModel):
    """Token listesi kaydi (ham token gosterilmez)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scopes: str
    is_active: bool
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class TokenCreated(TokenPublic):
    """Token uretimi yaniti — ham token yalnizca burada bir kez donulur."""

    token: str


PageNumber = Annotated[int, Field(ge=1, le=10_000)]
PerPage = Annotated[int, Field(ge=1, le=50)]
