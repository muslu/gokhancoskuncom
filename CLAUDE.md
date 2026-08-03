# gokhancoskun.com — Proje Kilavuzu

> Genel kodlama kurallari, yasaklar ve uretim standartlari **global** `~/.claude/CLAUDE.md`'dedir — burada tekrar edilmez.
> Bu dosya yalnizca **bu projeye ozel** mimari, adres, sema ve akislari icerir.
> Dinamik durum (acik gorevler, audit commit'leri, oturum notlari): [memory/](memory/MEMORY.md)

---

## Ne oldugu

Gokhan Coskun'un kisisel sitesi + blog. Sunucu tarafi render (Jinja2), ayri bir
yonetim paneli alt alan adinda, ve Claude'un blog yazabilmesi icin bir MCP sunucusu.

- **Site:** https://gokhancoskun.com (public SSR — anasayfa, blog, etiket, statik sayfa, iletisim)
- **Panel:** https://panel.gokhancoskun.com (cerez oturumu ile yonetim)
- **API:** panel alan adi altinda `/api/v1/...` (Bearer token — MCP ve harici istemciler)

Ucunu de **tek FastAPI uygulamasi** sunar; ayirma nginx `server` bloklari duzeyinde yapilir.
Apex'te `/panel`, `/giris` panele 301 yonlendirilir, `/api/` 404 doner.

---

## Projenin kapsami — site + panel DEGIL

Bu depo yalnizca web sitesi ve yonetim paneli degildir. **Ikinci ve esit onemde bir
is kolu var:** Gokhan'in gunluk isinde kullandigi CAM/CAD programlarina — basta
**Alphacam 2019 R1** — makro ve eklenti yazmak, sonra bunlari sitede blog yazisina
donusturmek.

### Calisma dongusu

1. Surekli tekrar eden bir isi Alphacam eklentisi/makrosu haline getiririz.
2. Gokhan **kendi tezgahinda/bilgisayarinda test eder**.
3. "Tamam, calisiyor — siteye yazi olarak ekle" dedinde: eklentiyi bir blog yazisina
   cevir. Beklenen kalite: **duzgun bir aciklama + animasyonlu SVG gorseller**.
   Ekran goruntusu degil — hareketi anlatan SVG (bkz. `templates/partials/cnc_animasyon.html`).
4. Yazi siteye `mcp_server/server.py` araclariyla eklenir (`blog_yazisi_olustur`,
   `blog_yazisi_guncelle`, `blog_yazisi_yayinla`). Once **taslak** olustur, Gokhan
   okuyup onaylayinca yayinla.

### ONCE ISLETIM SISTEMINI KONTROL ET

Gokhan **bazen Windows** kullanir (Alphacam Windows programidir), bazen Linux.
Herhangi bir is yapmadan once ortami dogrula — komutlari, yollari ve arac secimini
buna gore ayarla:

```bash
uname -s            # Linux mu?
python3 -c "import platform; print(platform.system(), platform.release())"
```

Windows'ta: `systemctl`/`su - postgres` yoktur, yollar `C:\...`, `python3` yerine
`python` veya `py -3.12` olabilir, kabuk PowerShell'dir. Sunucuya erisim yine
`excopan-ssh-web` MCP'si uzerinden calisir (o Linux sunucudur, degismez).

### Alphacam tarafi

Alphacam 2019 R1 otomasyonu VBA/COM uzerinden yapilir (`Licom.Alphacam` benzeri COM
nesnesi + APlus). **Kesin API detayini ilk gercek iste dogrula** — surumler arasi
farklar var; buraya tahminle sema yazma, calisan koddan ogrendigini yaz.

### ⚠ Blog yazisinda animasyonlu SVG — dogrudan gomme CALISMAZ

Yazi govdesi `src/services/markdown_service.py` icinde **bleach ile temizlenir** ve
`_ALLOWED_TAGS` listesinde **`svg` YOKTUR** — markdown'a yapistirilan inline SVG
sessizce tamamen silinir. Dogru yontem:

1. SVG'yi **ayri bir dosya** olarak medya dizinine koy (`/opt/gokhancoskun/media/...`).
2. Yaziya `<img>` ile gom: `![4 eksen kaba paso](/media/animasyon/kaba-paso.svg)`
   — `img` etiketi ve goreli yollar zaten izinli, CSP `img-src 'self'` ile uyumlu.
3. **CSS animasyonu `<img>` icindeki SVG'de calisir**, script calismaz (guvenli).
   `prefers-reduced-motion` kurali SVG'nin kendi belgesinde degerlendirildigi icin
   **medya SVG'sinin icine de** `@media (prefers-reduced-motion: reduce)` blogu koy —
   site.css'teki global kural oraya ulasmaz.

Alternatif (daha riskli, gerekmedikce yapma): `_ALLOWED_TAGS`'e kontrollu SVG
whitelist'i eklemek. O zaman `script`, `foreignObject` ve tum `on*` oznitelikleri
disarida birakilmali; animasyon icin `<style>` yerine SMIL (`<animate>`,
`<animateTransform>`) tercih edilmeli.

**Acik nokta:** Medya yukleme icin panelde/MCP'de hazir bir arac **yok** — SVG'ler
su an SSH ile kopyalanmali. Ilk blog yazisi isinde bunu cozmek gerekecek.

---

## Sunucu ve adresler

| Sey | Deger |
|---|---|
| Sunucu | `185.122.200.36` (root, MCP: `excopan-ssh-web`) |
| Proje koku | `/opt/gokhancoskun` (sahip `www-data:www-data`, mod 750) |
| systemd birimi | `gokhancoskun.service` (gunicorn + UvicornWorker, 2 worker) |
| Dinleme | `127.0.0.1:8002` |
| PostgreSQL | veritabani `gokhancoskundb`, kullanici `gokhancoskun` |
| Valkey | `127.0.0.1:6379`, **DB 3** (sunucuda baska projeler de var — DB numarasi cakismasin) |
| nginx conf | `/etc/nginx/sites-available/gokhancoskun.com.conf` |
| Sertifikalar | apex: `gokhancoskun.com` · panel: `panel.gokhancoskun.com` |
| Python | `python3.12` (sunucu 3.12.3) — venv: `/opt/gokhancoskun/venv` |

**Sunucu paylasimlidir.** Ayni makinede `musluorg`, `mailconf` ve baska siteler
calisir; nginx'in global ayarlari (`nginx.conf`, `snippets/`) **ortaktir**.
Global bir nginx direktifini degistirmeden once diger siteleri etkileyip
etkilemedigini dusun.

---

## Kod duzeni

```
main.py                  FastAPI uygulamasi — lifespan, middleware, hata sayfalari, /saglik
src/config.py            Pydantic Settings (.env)
src/colorlogger.py       ANSI renkli logger  → `from src.colorlogger import logger as lg`
src/crypto.py            Fernet parola sifreleme + API token hash'leme
src/db.py                Async PostgreSQL servisi (execute_query / execute_write)
src/cache.py             Async Valkey servisi (set_json / get_json / delete)
src/decorators.py        @rate_limit @cache @retry @timeit @log @before_after
src/middleware.py        SecurityHeadersMiddleware + ObservabilityMiddleware
src/auth.py              Cift kimlik: cerez oturumu (panel) + Bearer token (API)
src/templating.py        Jinja2 ortami, filtreler
src/models/schemas.py    Pydantic modelleri
src/models/repository.py Tum veri erisimi — SQL yalnizca burada
src/services/markdown_service.py  Markdown → bleach ile temizlenmis HTML
src/routers/public.py    Public SSR + RSS/sitemap/robots
src/routers/panel.py     Panel CRUD (PRG deseni)
src/routers/api.py       REST API (Bearer)
mcp_server/server.py     15 MCP araci — Claude uzerinden blog yazma
migrations/001_init.sql  Sema
deploy/                  nginx conf, systemd unit, deploy.sh, panel-ssl.sh
```

**SQL yalnizca `src/models/repository.py` icinde.** Router'lar dogrudan sorgu yazmaz.

---

## Sema (migrations/001_init.sql)

`users` · `tags` · `posts` · `post_tags` · `pages` · `profile` · `contact_messages`
· `api_tokens` · `audit_log`

Onemli indeksler: `posts` icin partial (yayinda/one cikan), `search_tsv` GIN,
`title` uzerinde pg_trgm GIN. Eklentiler: `pg_trgm`, `unaccent` (superuser kurar).

---

## URL sozlesmesi — Turkce yollar

Yollar ve sablon adlari **Turkce**: `/blog`, `/etiket/{slug}`, `/iletisim`,
`/giris`, `/panel/yazilar`, `/saglik`. Sablonlar: `anasayfa.html`,
`blog_liste.html`, `blog_detay.html`, `sayfa.html`, `hata.html`,
`panel/taban.html`, `panel/gosterge.html` …

Yeni yol eklerken bu dile sadik kal — yarisi Ingilizce yarisi Turkce bir URL
haritasi olusturma.

---

## İletişim formu

Mesaj **iki yere birden** gider ve ikisi birbirinden bagimsizdir:

1. **Veritabani** (`contact_messages`) → panelde `/panel/mesajlar` altinda listelenir.
2. **E-posta** → `siteform@gokhancoskun.com` adresinden `gokhancoskun1983@gmail.com`'a.
   `Reply-To` ziyaretcinin adresine ayarlanir; `From` **site adresi kalir** — aksi
   halde SPF/DKIM hizalanmaz ve mesaj spam'e duser.

E-posta gonderimi `BackgroundTasks` uzerinden yapilir (SMTP bloklayici, ziyaretci
beklemesin) ve **hata firlatmaz**: SMTP coksede mesaj zaten DB'ye yazilmistir.

Mail sunucusu ayni makinede: Postfix → `127.0.0.1:25`, kimlik dogrulama yok.
`siteform@gokhancoskun.com` sanal kutusu `maildb.virtual_users` icinde
(`domain_id = 9`, parola semasi **BLF-CRYPT**), kutu `/var/vmail/gokhancoskun.com/siteform`.
DNS tarafi hazir: MX → `mail.gokhancoskun.com`, SPF `v=spf1 mx a:mail.gokhancoskun.com ~all`,
DKIM `mail._domainkey` (`d=gokhancoskun.com`), DMARC `p=quarantine`.

### Bot korumasi — captcha YOK

reCAPTCHA bilincli olarak kullanilmadi: harici script CSP'yi gevsetmeyi gerektirir,
ucuncu tarafa veri gonderir ve bulmacalar WCAG acisindan sorunludur. Yerine uc katman:

1. **Honeypot** (`website` alani) — sablonda gizli.
2. **Imzali zaman token'i** (`src/services/bot_koruma.py`) — form render edildigi an
   JWT_SECRET ile imzalanir; gonderim `FORM_MIN_SECONDS`–`FORM_MAX_SECONDS` araliginin
   disindaysa reddedilir.
3. `@rate_limit(requests=5, window_seconds=600)`.

**Bu yuzden `/iletisim` GET route'u `@cache_response` ALMAZ** (genel "GET'lerde cache
zorunlu" kuralinin bilincli istisnasi): onbelleklenen HTML ayni token'i dakikalarca
herkese dagitir ve "cok hizli gonderim" olcumu anlamini yitirir. Sayfa bu yuzden
catch-all `/{sayfa_slug}` yerine **kendi route'unda** karsilanir.

---

## Gotchas

- **CSP inline script hash'i.** `base.html` icindeki tek inline script
  (tema onyukleyici) CSP'de sha256 ile beyaz listede. Scripti **bir karakter bile**
  degistirirsen hash bozulur ve tema calismaz. Yeni hash:
  `python3 scripts/csp_hash.py` → cikan degeri nginx conf'taki `script-src`'ye yaz.
- **`Cache-Control` tek sahibi nginx** — `$cc` deseni. Location'lar yalnizca
  `set $cc "..."` yapar; **location icine `add_header` KOYMA** (miras alinmaz,
  o yanittaki HSTS/CSP dahil tum baslıklari sessizce dusurur). Ayni sebeple
  `Alt-Svc` de `$altsvc` degiskeni uzerinden, sitemap'te bosaltilarak yonetilir.
- **`proxy_hide_header`** ile arka ucun `Cache-Control` / `HSTS` /
  `X-Content-Type-Options` kopyalari gizlenir — bu basliklarin tek sahibi nginx.
- **SQL'de PostgreSQL `::` cast'i kullanma — `CAST(... AS ...)` yaz.**
  SQLAlchemy `text()` icinde `:param::tip` yazildiginda `::`'yi escape sanip
  parametreyi **degistirmeden birakiyor**; PostgreSQL'e ham `:param` gidiyor ve
  sorgu `syntax error at or near ":"` ile patliyor. Bu yuzden panelden ve MCP'den
  yazi eklemek bir sure tamamen kirikti (`slug_exists` icindeki
  `:exclude_id::bigint`). Ayni tuzak `create_api_token`'da da vardi.
  NULL parametrede tip belirtmek gerekiyorsa `CAST(:x AS BIGINT)` kullan.
- **Valkey DB 3** — sunucu paylasimli, baska DB numarasini kullanma.
- **Panel sertifikasi** alinana kadar nginx panel blogunda gecici olarak apex
  sertifikasi kullanilir; `deploy/scripts/panel-ssl.sh` bunu kendi sertifikasina gecirir.
- **RSS kaldirildi.** `/rss.xml` nginx'te `410 Gone` doner (301 degil — kaynak kalici
  olarak yok). Route, `<link rel="alternate">` ve alt menu bagi da silindi.
- **Ust ve alt menu ayni sirada** tutulur (Anasayfa → Blog → menu sayfalari).
  Birini degistirirken digerini de degistir; kullanici ikisini karsilastiriyor.
- **`scrollbar-gutter: stable`** (`html`) — kisa sayfalarda dikey kaydirma cubugu
  kaybolunca tum duzen ~15px yana kayiyordu. Kaldirma, "tasarim oynuyor" hatasi geri gelir.
- **CNC animasyonu inline SVG** (`templates/partials/cnc_animasyon.html`), `<img>` degil:
  site.css'teki global `prefers-reduced-motion` kurali yalnizca ayni belgedeki ogelere
  isler. Sinif adlari `cnc-` onekli — SVG icindeki `<style>` global CSS kapsamina girer.

---

## Deploy akisi

```bash
# 1) dosyalari sunucuya kopyala  → /opt/gokhancoskun
# 2) sunucuda root olarak:
bash /opt/gokhancoskun/deploy/scripts/deploy.sh      # idempotent: paketler, DB, venv, systemd, nginx
bash /opt/gokhancoskun/deploy/scripts/panel-ssl.sh   # panel sertifikasi (DNS hazir olmali)
```

`deploy.sh` `.env` **varsa korur**, yoksa uretir ve ilk yonetici parolasini
`/opt/gokhancoskun/.ilk-parola` dosyasina yazar (giris sonrasi degistir + sil).

Kontrol:
```bash
systemctl status gokhancoskun.service
journalctl -u gokhancoskun.service -f
curl -s http://127.0.0.1:8002/saglik
```

---

## Yerel calisma

Sunucu Python 3.12 kullanir; kod `datetime.UTC` gibi 3.11+ ozellikleri icerir —
**3.10 ile import bile edilemez.** Yerel test ortamini `python3.12` ile kur.
