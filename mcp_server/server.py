"""gokhancoskun.com MCP sunucusu.

Claude icinden blog yazisi olusturmayi, duzenlemeyi ve yayinlamayi saglar.
Sunucu, panelde uretilen API token'i ile HTTPS uzerinden REST API'ye baglanir —
veritabanina dogrudan erisim YOKTUR.

Kurulum:
    GC_API_BASE  = https://panel.gokhancoskun.com
    GC_API_TOKEN = panelden uretilen token (Panel > API / MCP)

Calistirma:
    python3.12 -m mcp_server.server
"""

import os
import sys
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ------------------------------------------------------------------
# Yapilandirma — .env dosyasindan okunur, hardcode yasak
# ------------------------------------------------------------------
PROJE_KOK = Path(__file__).resolve().parent.parent


def _env_yukle() -> None:
    """Proje kokundeki .env dosyasini ortama yukler (harici bagimlilik olmadan)."""
    env_yolu = PROJE_KOK / ".env"
    if not env_yolu.exists():
        return
    for satir in env_yolu.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        anahtar = anahtar.strip()
        if anahtar not in os.environ:
            os.environ[anahtar] = deger.strip().strip('"').strip("'")


_env_yukle()

API_BASE = os.environ.get("GC_API_BASE", "https://panel.gokhancoskun.com").rstrip("/")
API_TOKEN = os.environ.get("GC_API_TOKEN", "")
ZAMAN_ASIMI = float(os.environ.get("GC_API_TIMEOUT", "30"))

mcp = FastMCP(
    "gokhancoskun-blog",
    instructions=(
        "gokhancoskun.com kişisel sitesinin blog yönetimi. "
        "Yazılar Markdown olarak yazılır; başlıklar ## ile başlar (# kullanma — "
        "sayfa h1'i başlıktan üretilir). Yeni yazılar varsayilan olarak TASLAK "
        "oluşturulur; kullanıcı açıkça istemedikçe yayınlama."
    ),
)


# ------------------------------------------------------------------
# HTTP yardimcilari
# ------------------------------------------------------------------
class ApiHatasi(Exception):
    """API'den donen hata yanitlarini temsil eder."""


async def _istek(
    yontem: str,
    yol: str,
    *,
    govde: dict[str, Any] | None = None,
    sorgu: dict[str, Any] | None = None,
) -> Any:
    """API'ye kimlik dogrulamali istek gonderir ve JSON yaniti dondurur."""
    if not API_TOKEN:
        raise ApiHatasi(
            "GC_API_TOKEN tanımlı değil. Panel > API / MCP sayfasından token üretip "
            "proje kökündeki .env dosyasına ekleyin."
        )

    basliklar = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Accept": "application/json",
        "User-Agent": "gokhancoskun-mcp/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=ZAMAN_ASIMI, follow_redirects=False) as istemci:
            yanit = await istemci.request(
                yontem,
                f"{API_BASE}{yol}",
                json=govde,
                params={k: v for k, v in (sorgu or {}).items() if v is not None},
                headers=basliklar,
            )
    except httpx.TimeoutException as exc:
        raise ApiHatasi(f"API zaman aşımına uğradı ({ZAMAN_ASIMI}s): {API_BASE}{yol}") from exc
    except httpx.HTTPError as exc:
        raise ApiHatasi(f"API'ye bağlanılamadı: {exc}") from exc

    if yanit.status_code == 401:
        raise ApiHatasi("Token geçersiz veya süresi dolmuş. Panelden yeni token üretin.")
    if yanit.status_code == 403:
        raise ApiHatasi(
            f"Token bu işlem için yetkili değil. Panelden gerekli kapsamı verin. "
            f"Sunucu yanıtı: {yanit.text[:200]}"
        )
    if yanit.status_code == 404:
        raise ApiHatasi("Kayıt bulunamadı — slug'ı `blog_yazisi_listele` ile doğrulayın.")
    if yanit.status_code == 429:
        raise ApiHatasi("Çok fazla istek gönderildi. Birkaç dakika bekleyip tekrar deneyin.")
    if yanit.status_code >= 400:
        raise ApiHatasi(f"API hatası ({yanit.status_code}): {yanit.text[:400]}")

    try:
        return yanit.json()
    except ValueError as exc:
        raise ApiHatasi(f"API geçersiz JSON döndürdü: {yanit.text[:200]}") from exc


def _yazi_ozeti(yazi: dict[str, Any]) -> str:
    """Yazi kaydini okunabilir ozet metnine cevirir."""
    durum = "YAYINDA" if yazi.get("status") == "published" else "TASLAK"
    satirlar = [
        f"Başlık : {yazi.get('title')}",
        f"Slug   : {yazi.get('slug')}",
        f"Durum  : {durum}",
        f"Adres  : https://gokhancoskun.com/blog/{yazi.get('slug')}",
    ]
    if yazi.get("tags"):
        satirlar.append(f"Etiket : {', '.join(yazi['tags'])}")
    if yazi.get("reading_minutes"):
        satirlar.append(f"Okuma  : {yazi['reading_minutes']} dk")
    if yazi.get("summary"):
        satirlar.append(f"Özet   : {yazi['summary']}")
    return "\n".join(satirlar)


# ------------------------------------------------------------------
# Araclar
# ------------------------------------------------------------------
@mcp.tool()
async def blog_baglanti_testi() -> str:
    """API bağlantısını ve token yetkilerini doğrular.

    Bir sorun yaşandığında ilk çalıştırılacak araçtır.
    """
    try:
        veri = await _istek("GET", "/api/v1/kimlik")
    except ApiHatasi as exc:
        return f"BAĞLANTI BAŞARISIZ\n{exc}\n\nAdres: {API_BASE}"
    return (
        "BAĞLANTI BAŞARILI\n"
        f"Adres    : {API_BASE}\n"
        f"Token    : {veri['token_adi']}\n"
        f"Kullanıcı: {veri['kullanici']} ({veri['rol']})\n"
        f"Yetkiler : {', '.join(veri['yetkiler'])}"
    )


@mcp.tool()
async def blog_yazisi_olustur(
    baslik: str,
    icerik: str,
    ozet: str = "",
    etiketler: str = "",
    kapak_gorseli: str = "",
    meta_aciklama: str = "",
    yayinla: bool = False,
    one_cikar: bool = False,
) -> str:
    """Yeni blog yazısı oluşturur.

    Args:
        baslik: Yazı başlığı (3-220 karakter). Slug bundan otomatik üretilir.
        icerik: Markdown gövde. Başlıklar `##` ile başlamalı — `#` kullanma,
            sayfa h1'i `baslik` alanından üretilir. Kod blokları, tablo, liste
            ve bağlantı desteklenir; ham HTML güvenlik için temizlenir.
        ozet: Liste ve arama sonuçlarında görünen özet. Boşsa içerikten üretilir.
        etiketler: Virgülle ayrılmış etiketler, ör. "python, fastapi". En fazla 12.
        kapak_gorseli: Kapak görseli adresi (tam URL veya /media/… yolu).
        meta_aciklama: SEO açıklaması (en fazla 300 karakter). Boşsa özet kullanılır.
        yayinla: True ise doğrudan yayına alınır. Varsayılan False (taslak) —
            kullanıcı açıkça istemedikçe True yapma.
        one_cikar: True ise anasayfada öne çıkan yazılar bölümünde gösterilir.

    Returns:
        Oluşturulan yazının özeti (slug, durum, adres).
    """
    govde: dict[str, Any] = {
        "title": baslik.strip(),
        "content_md": icerik,
        "status": "published" if yayinla else "draft",
        "is_featured": one_cikar,
        "tags": [e.strip() for e in etiketler.split(",") if e.strip()][:12],
    }
    if ozet.strip():
        govde["summary"] = ozet.strip()[:500]
    if kapak_gorseli.strip():
        govde["cover_image"] = kapak_gorseli.strip()
    if meta_aciklama.strip():
        govde["meta_description"] = meta_aciklama.strip()[:300]

    try:
        yazi = await _istek("POST", "/api/v1/yazilar", govde=govde)
    except ApiHatasi as exc:
        return f"HATA: {exc}"

    durum_notu = (
        "Yazı yayında ve herkese açık."
        if yayinla
        else "Yazı TASLAK olarak kaydedildi — yayınlamak için `blog_yazisi_yayinla` kullanın."
    )
    return f"Yazı oluşturuldu.\n\n{_yazi_ozeti(yazi)}\n\n{durum_notu}"


@mcp.tool()
async def blog_yazisi_guncelle(
    slug: str,
    baslik: str = "",
    icerik: str = "",
    ozet: str = "",
    etiketler: str = "",
    kapak_gorseli: str = "",
    meta_aciklama: str = "",
    one_cikar: bool | None = None,
) -> str:
    """Mevcut bir blog yazısını günceller (yalnızca dolu alanlar değiştirilir).

    Args:
        slug: Güncellenecek yazının slug'ı. `blog_yazisi_listele` ile bulunabilir.
        baslik: Yeni başlık. Boş bırakılırsa değişmez. Slug SEO için sabit kalır.
        icerik: Yeni Markdown gövde. Boş bırakılırsa değişmez. Bu alan verilirse
            içerik TAMAMEN değiştirilir — kısmi düzenleme için önce
            `blog_yazisi_getir` ile mevcut içeriği okuyun.
        ozet: Yeni özet. Boş bırakılırsa değişmez.
        etiketler: Virgülle ayrılmış yeni etiket listesi. Verilirse mevcut
            etiketlerin TAMAMI bununla değiştirilir.
        kapak_gorseli: Yeni kapak görseli adresi.
        meta_aciklama: Yeni SEO açıklaması.
        one_cikar: True/False verilirse öne çıkarma durumu değişir; None ise dokunulmaz.

    Returns:
        Güncellenen yazının özeti.
    """
    govde: dict[str, Any] = {}
    if baslik.strip():
        govde["title"] = baslik.strip()
    if icerik.strip():
        govde["content_md"] = icerik
    if ozet.strip():
        govde["summary"] = ozet.strip()[:500]
    if etiketler.strip():
        govde["tags"] = [e.strip() for e in etiketler.split(",") if e.strip()][:12]
    if kapak_gorseli.strip():
        govde["cover_image"] = kapak_gorseli.strip()
    if meta_aciklama.strip():
        govde["meta_description"] = meta_aciklama.strip()[:300]
    if one_cikar is not None:
        govde["is_featured"] = one_cikar

    if not govde:
        return "HATA: Güncellenecek alan verilmedi. En az bir alan doldurun."

    try:
        yazi = await _istek("PATCH", f"/api/v1/yazilar/{slug}", govde=govde)
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"Yazı güncellendi.\n\n{_yazi_ozeti(yazi)}"


@mcp.tool()
async def blog_yazisi_listele(
    durum: str = "",
    ara: str = "",
    etiket: str = "",
    adet: int = 20,
    sayfa: int = 1,
) -> str:
    """Blog yazılarını listeler (taslaklar dahil).

    Args:
        durum: "draft" (taslak) veya "published" (yayında). Boş: tümü.
        ara: Başlık ve içerikte aranacak terim.
        etiket: Etiket slug'ı ile filtreleme, ör. "python".
        adet: Sayfa başına kayıt (1-50).
        sayfa: Sayfa numarası.

    Returns:
        Yazı listesi — slug, durum, tarih ve görüntülenme bilgisiyle.
    """
    sorgu = {
        "sayfa": max(1, sayfa),
        "adet": max(1, min(50, adet)),
        "durum": durum.strip() or None,
        "ara": ara.strip() or None,
        "etiket": etiket.strip() or None,
    }
    try:
        veri = await _istek("GET", "/api/v1/yazilar", sorgu=sorgu)
    except ApiHatasi as exc:
        return f"HATA: {exc}"

    if not veri["items"]:
        return "Kriterlere uyan yazı bulunamadı."

    satirlar = [
        f"Toplam {veri['total']} yazı — sayfa {veri['page']}/{veri['pages']}",
        "",
    ]
    for y in veri["items"]:
        isaret = "●" if y["status"] == "published" else "○"
        tarih = (y.get("published_at") or y.get("updated_at") or "")[:10]
        satirlar.append(
            f"{isaret} {y['slug']}\n"
            f"   {y['title']}\n"
            f"   {tarih} · {y['reading_minutes']} dk · {y['view_count']} görüntülenme"
            + (f" · {', '.join(y['tags'])}" if y.get("tags") else "")
        )
    satirlar.append("")
    satirlar.append("● yayında   ○ taslak")
    return "\n".join(satirlar)


@mcp.tool()
async def blog_yazisi_getir(slug: str) -> str:
    """Tek bir yazının tam Markdown içeriğini getirir.

    Yazıyı düzenlemeden önce mevcut içeriği okumak için kullanın.

    Args:
        slug: Yazının slug'ı.

    Returns:
        Yazının üstverisi ve tam Markdown gövdesi.
    """
    try:
        yazi = await _istek("GET", f"/api/v1/yazilar/{slug}")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"{_yazi_ozeti(yazi)}\n\n--- MARKDOWN İÇERİK ---\n\n{yazi['content_md']}"


@mcp.tool()
async def blog_yazisi_yayinla(slug: str) -> str:
    """Taslak yazıyı yayına alır — herkese açık hale getirir.

    Args:
        slug: Yayınlanacak yazının slug'ı.

    Returns:
        Yayınlanan yazının özeti ve canlı adresi.
    """
    try:
        yazi = await _istek("POST", f"/api/v1/yazilar/{slug}/yayinla")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"Yazı yayınlandı.\n\n{_yazi_ozeti(yazi)}"


@mcp.tool()
async def blog_yazisi_taslaga_al(slug: str) -> str:
    """Yayındaki yazıyı taslağa çevirir — siteden kaldırır ama silmez.

    Args:
        slug: Taslağa alınacak yazının slug'ı.

    Returns:
        İşlem sonucu.
    """
    try:
        yazi = await _istek("POST", f"/api/v1/yazilar/{slug}/taslaga-al")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"Yazı taslağa alındı, siteden kaldırıldı.\n\n{_yazi_ozeti(yazi)}"


@mcp.tool()
async def blog_yazisi_sil(slug: str, onay: bool = False) -> str:
    """Bir yazıyı KALICI olarak siler. Geri alınamaz.

    Args:
        slug: Silinecek yazının slug'ı.
        onay: Güvenlik önlemi — silmek için True olmalı. Kullanıcı açıkça
            silmeyi onaylamadan True yapma. Yayından kaldırmak yeterliyse
            `blog_yazisi_taslaga_al` tercih edin.

    Returns:
        İşlem sonucu.
    """
    if not onay:
        return (
            f"Silme işlemi yapılmadı: `onay` parametresi False.\n"
            f"“{slug}” kalıcı olarak silinecekse onay=True ile tekrar çağırın.\n"
            f"Yalnızca yayından kaldırmak istiyorsanız `blog_yazisi_taslaga_al` kullanın."
        )
    try:
        await _istek("DELETE", f"/api/v1/yazilar/{slug}")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"“{slug}” kalıcı olarak silindi."


@mcp.tool()
async def etiketleri_listele() -> str:
    """Sitede kullanılan etiketleri yazı sayılarıyla birlikte listeler.

    Yeni yazıya etiket verirken mevcut etiketlerle tutarlı olmak için kullanın.
    """
    try:
        etiketler = await _istek("GET", "/api/v1/etiketler")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    if not etiketler:
        return "Henüz etiket yok."
    return "\n".join(f"{e['name']} ({e['slug']}) — {e['post_count']} yazı" for e in etiketler)


@mcp.tool()
async def sayfa_listele() -> str:
    """Düzenlenebilir statik sayfaları (Hakkımda, İletişim) listeler."""
    try:
        sayfalar = await _istek("GET", "/api/v1/sayfalar")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    satirlar = []
    for s in sayfalar:
        durum = "yayında" if s["is_published"] else "gizli"
        satirlar.append(
            f"{s['slug']} — {s['title']} ({durum})\n"
            f"   https://gokhancoskun.com/{s['slug']}\n"
            f"   {len(s['content_md'])} karakter içerik"
        )
    return "\n".join(satirlar) if satirlar else "Sayfa yok."


@mcp.tool()
async def sayfa_getir(slug: str) -> str:
    """Statik bir sayfanın tam Markdown içeriğini getirir.

    Args:
        slug: Sayfa slug'ı — "hakkimda" veya "iletisim".
    """
    try:
        sayfalar = await _istek("GET", "/api/v1/sayfalar")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    for s in sayfalar:
        if s["slug"] == slug:
            return (
                f"Sayfa : {s['title']} (/{s['slug']})\n"
                f"Durum : {'yayında' if s['is_published'] else 'gizli'}\n\n"
                f"--- MARKDOWN İÇERİK ---\n\n{s['content_md']}"
            )
    return f"HATA: “{slug}” sayfası bulunamadı. `sayfa_listele` ile mevcut sayfaları görün."


@mcp.tool()
async def sayfa_guncelle(
    slug: str, icerik: str = "", baslik: str = "", meta_aciklama: str = ""
) -> str:
    """Statik sayfanın (Hakkımda, İletişim) içeriğini günceller.

    Args:
        slug: Sayfa slug'ı — "hakkimda" veya "iletisim".
        icerik: Yeni Markdown gövde. Verilirse içerik TAMAMEN değiştirilir —
            önce `sayfa_getir` ile mevcut içeriği okuyun.
        baslik: Yeni sayfa başlığı.
        meta_aciklama: SEO açıklaması.

    Returns:
        İşlem sonucu.
    """
    govde: dict[str, Any] = {}
    if icerik.strip():
        govde["content_md"] = icerik
    if baslik.strip():
        govde["title"] = baslik.strip()
    if meta_aciklama.strip():
        govde["meta_description"] = meta_aciklama.strip()[:300]

    if not govde:
        return "HATA: Güncellenecek alan verilmedi."

    try:
        sonuc = await _istek("PATCH", f"/api/v1/sayfalar/{slug}", govde=govde)
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return (
        f"Sayfa güncellendi: {sonuc['title']}\n"
        f"Adres: https://gokhancoskun.com/{sonuc['slug']}"
    )


@mcp.tool()
async def profil_getir() -> str:
    """Sitedeki kişisel bilgileri (ad, unvan, biyografi, iletişim) getirir."""
    try:
        p = await _istek("GET", "/api/v1/profil")
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    satirlar = [
        f"Ad soyad : {p['full_name']}",
        f"Unvan    : {p['title'] or '—'}",
        f"Tanıtım  : {p['tagline'] or '—'}",
        f"E-posta  : {p['email'] or '—'}",
        f"Konum    : {p['location'] or '—'}",
    ]
    if p.get("socials"):
        satirlar.append(f"Sosyal   : {', '.join(f'{k}={v}' for k, v in p['socials'].items())}")
    satirlar.append(f"\n--- BİYOGRAFİ (Markdown) ---\n\n{p['bio_md'] or '(boş)'}")
    return "\n".join(satirlar)


@mcp.tool()
async def profil_guncelle(
    ad_soyad: str = "",
    unvan: str = "",
    kisa_tanitim: str = "",
    biyografi: str = "",
    eposta: str = "",
    telefon: str = "",
    konum: str = "",
) -> str:
    """Sitedeki kişisel bilgileri günceller (yalnızca dolu alanlar değişir).

    Args:
        ad_soyad: Ad ve soyad.
        unvan: Meslek/unvan — anasayfada adın üstünde görünür.
        kisa_tanitim: Anasayfa girişi ve arama sonuçlarındaki açıklama.
        biyografi: Markdown biyografi metni.
        eposta: İletişim e-postası.
        telefon: İletişim telefonu.
        konum: Şehir/ülke.

    Returns:
        İşlem sonucu.
    """
    eslesme = {
        "full_name": ad_soyad,
        "title": unvan,
        "tagline": kisa_tanitim,
        "bio_md": biyografi,
        "email": eposta,
        "phone": telefon,
        "location": konum,
    }
    govde = {k: v.strip() for k, v in eslesme.items() if v.strip()}
    if not govde:
        return "HATA: Güncellenecek alan verilmedi."

    try:
        p = await _istek("PATCH", "/api/v1/profil", govde=govde)
    except ApiHatasi as exc:
        return f"HATA: {exc}"
    return f"Kişisel bilgiler güncellendi.\nGüncellenen alanlar: {', '.join(govde)}\nAd: {p['full_name']}"


def main() -> None:
    """MCP sunucusunu stdio aktarimi ile calistirir."""
    if not API_TOKEN:
        print(
            "UYARI: GC_API_TOKEN tanımlı değil. Panel > API / MCP sayfasından "
            "token üretip .env dosyasına ekleyin.",
            file=sys.stderr,
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
