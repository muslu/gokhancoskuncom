"""Jinja2 sablon motoru, ozel filtreler ve ortak sablon baglami."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from src.config import settings
from src.models import repository as repo
from src.services.markdown_service import make_slug, plain_text

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

_AYLAR = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)

_SOSYAL_ADLAR = {
    "github": "GitHub",
    "linkedin": "LinkedIn",
    "x": "X",
    "twitter": "Twitter",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "mastodon": "Mastodon",
    "website": "Web sitesi",
}

# Statik varliklarin cache'ini kirmak icin surum damgasi (deploy'da degisir)
ASSET_VERSION = datetime.now(UTC).strftime("%Y%m%d%H%M")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def filtre_tarih(value: datetime | None, kisa: bool = False) -> str:
    """Tarihi Türkçe olarak biçimlendirir (ör. 3 Ağustos 2026)."""
    if value is None:
        return ""
    if kisa:
        return value.strftime("%d.%m.%Y")
    return f"{value.day} {_AYLAR[value.month - 1]} {value.year}"


def filtre_slugla(value: str) -> str:
    """Etiket adindan URL slug'i uretir."""
    return make_slug(value or "", max_length=80)


def filtre_sosyal_ad(value: str) -> str:
    """Sosyal medya anahtarini okunabilir ada cevirir."""
    return _SOSYAL_ADLAR.get(value, value.title())


def _temizle(value: Any) -> Any:
    """JSON-LD icin None ve bos degerleri ozyinelemeli olarak atar."""
    if isinstance(value, dict):
        cleaned = {k: _temizle(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        items = [_temizle(v) for v in value]
        return [v for v in items if v not in (None, "", [], {})]
    return value


def filtre_jsonld(value: dict[str, Any]) -> Markup:
    """Sozlugu guvenli JSON-LD metnine cevirir (`</script>` kacisli)."""
    payload = json.dumps(_temizle(value), ensure_ascii=False, separators=(",", ":"), default=str)
    # XSS: JSON govdesi icinde script etiketinin erken kapanmasini engelle
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(payload)


def filtre_duz_metin(value: str) -> str:
    """HTML'den duz metin cikarir (ozet icin)."""
    return plain_text(value)


templates.env.filters["tarih"] = filtre_tarih
templates.env.filters["slugla"] = filtre_slugla
templates.env.filters["sosyal_ad"] = filtre_sosyal_ad
templates.env.filters["jsonld"] = filtre_jsonld
templates.env.filters["duz_metin"] = filtre_duz_metin
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True


def kirinti(*ogeler: tuple[str, str]) -> list[dict[str, Any]]:
    """schema.org BreadcrumbList ogelerini uretir: (ad, mutlak_url) ciftleri."""
    return [
        {"@type": "ListItem", "position": i, "name": ad, "item": url}
        for i, (ad, url) in enumerate(ogeler, start=1)
    ]


async def temel_baglam(request: Request, aktif: str = "") -> dict[str, Any]:
    """Her public sayfada gereken ortak sablon degiskenlerini dondurur."""
    return {
        "request": request,
        "profil": await repo.get_profile(),
        "menu_sayfalari": await repo.list_pages(menu_only=True),
        "site_url": settings.site_url.rstrip("/"),
        "panel_url": settings.panel_url.rstrip("/"),
        "asset_version": ASSET_VERSION,
        "yil": datetime.now(UTC).year,
        "aktif": aktif,
    }
