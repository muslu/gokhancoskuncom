"""Markdown -> guvenli HTML donusumu, slug uretimi ve okuma suresi hesabi."""

import re

import bleach
import markdown as md
from slugify import slugify

from src.colorlogger import logger

_ALLOWED_TAGS = [
    "p", "br", "hr", "strong", "em", "del", "s", "u", "blockquote",
    "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "a", "img", "figure", "figcaption",
    "code", "pre", "kbd", "samp", "var",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    "span", "div", "sup", "sub", "abbr",
]

_ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height", "loading", "decoding"],
    "code": ["class"],
    "pre": ["class"],
    "span": ["class"],
    "div": ["class"],
    "th": ["scope", "colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "abbr": ["title"],
}

_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]

_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def render_markdown(text: str) -> str:
    """Markdown metnini XSS'e karsi temizlenmis HTML'e cevirir."""
    if not text:
        return ""
    try:
        html = md.markdown(
            text,
            extensions=["extra", "sane_lists", "smarty", "codehilite", "toc"],
            extension_configs={"codehilite": {"guess_lang": False, "css_class": "kod"}},
            output_format="html",
        )
    except (ValueError, TypeError) as exc:
        logger.error("Markdown donusum hatasi: %s", exc)
        return ""

    cleaned = bleach.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    # Dis baglantilara guvenlik nitelikleri ekle
    return bleach.linkify(
        cleaned, callbacks=[_external_link_attrs], skip_tags=["pre", "code"], parse_email=False
    )


def _external_link_attrs(attrs: dict, new: bool = False) -> dict:
    """Dis baglantilara `rel="noopener noreferrer"` ve `target="_blank"` ekler."""
    href = attrs.get((None, "href"), "")
    if href.startswith("http") and "gokhancoskun.com" not in href:
        attrs[(None, "target")] = "_blank"
        attrs[(None, "rel")] = "noopener noreferrer"
    return attrs


def make_slug(title: str, max_length: int = 200) -> str:
    """Baslikten URL-guvenli slug uretir (Turkce karakterler donusturulur)."""
    slug = slugify(title, max_length=max_length, word_boundary=True, lowercase=True)
    return slug or "yazi"


def plain_text(html: str) -> str:
    """HTML'den duz metin cikarir (ozet/meta uretimi icin)."""
    return _WS_RE.sub(" ", _TAG_STRIP_RE.sub(" ", html or "")).strip()


def make_summary(content_md: str, limit: int = 200) -> str:
    """Icerikten otomatik ozet uretir; kelime ortasinda kesmez."""
    text = plain_text(render_markdown(content_md))
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


def reading_minutes(content_md: str, wpm: int = 200) -> int:
    """Icerigin tahmini okuma suresini dakika olarak dondurur (en az 1)."""
    words = len(plain_text(render_markdown(content_md)).split())
    return max(1, round(words / wpm))
