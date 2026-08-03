---
name: deploy-durumu
description: gokhancoskun.com uretim deploy durumu — neyin canli oldugu ve neyin acik kaldigi
metadata:
  type: project
---

> Not: Sunucu adresleri, port'lar, servis adlari, deploy akisi, iletisim formu mimarisi
> ve kod gotchas'lari proje `CLAUDE.md`'sinde tutuluyor — burada tekrar yok.
> Burasi yalnizca **degisken durum**.

**Canli (2026-08-03):** `gokhancoskun.service` `active`+`enabled`, `/saglik` → postgres ✓
valkey ✓, apex ve www HTTP/2+HTTP/3, gzip acik, HSTS+CSP basiliyor, `sitemap.xml`
`Alt-Svc` almiyor. Erisilebilirlik (lighthouse 12): `/`, `/blog`, `/hakkimda`,
`/iletisim` → **hepsi 100/100**. Blog **detay** tipi henuz olculemedi (hic yayinlanmis
yazi yok).

**Sunucuda tamamlandi:** `siteform@gokhancoskun.com` sanal posta kutusu olusturuldu
(`maildb.virtual_users` id=15, domain_id=9). Parola: **`/root/.siteform-parola`** (mod 600).
Uctan uca dogrulandi — Gmail `250 OK` ile kabul etti, teslim edilen mesajda
`DKIM-Signature: d=gokhancoskun.com` var, kutu `/var/vmail/gokhancoskun.com/siteform`
otomatik olustu. Kutuda iki test mesaji duruyor (silinebilir).

**Deploy artik git ile:** `/opt/gokhancoskun` bir git deposu (`origin` → GitHub,
`--depth=1`). Guncelleme: `git fetch origin main && git reset --hard origin/main`.
Dizin `www-data`'nin, root git calistirdigi icin
`git config --global --add safe.directory /opt/gokhancoskun` gerekti.
`.env`, `media/` ve `.ilk-parola` git'te olmadigindan checkout onlara dokunmaz.

**2026-08-03 deploy edildi ve canlida dogrulandi:** ust/alt menu ayni sirada,
`scrollbar-gutter` duzeltmesi, RSS → 410, CNC animasyonu anasayfada, iletisim formu
e-posta + bot korumasi. Canli form testi: cok hizli gonderim 422 ✓, honeypot sessizce
yutuldu ✓, gercek gonderim hem `contact_messages`'a yazildi hem Gmail'e `status=sent`
ile ulasti ✓. Panel SSL alindi (Let's Encrypt, `CN=panel.gokhancoskun.com`,
1 Kasim 2026'ya kadar, otomatik yenileme kurulu). Erisilebilirlik yeniden olculdu:
`/` ve `/iletisim` → 100/100.

**2026-08-03 ikinci dalga (hepsi canlida dogrulandi):** WhatsApp sabit bagi,
Alphacam kullanim serisi (9 yazi + 9 animasyonlu SVG, toplam 10 yazi yayinda),
Google Search Console dogrulama + GA4 (`G-37SYYCK7EM`), OG gorseli ve
apple-touch-icon (ikisi de eksikti), panelden SMTP ile mesaj yanitlama
(migration 002), IP basina gunde bir okunma sayaci, API/MCP sayfasinin
adim adim yeniden yazimi, panel alan adinin yalnizca yonetim yollarini sunmasi.

**2026-08-03 kapatilan iki bulgu:**
`Server` header'i artik `muslu@makdos` — deger ortak `/etc/nginx/nginx.conf`
satir 24'te (`more_set_headers`), yani **sunucudaki 10 sitenin hepsini** etkiler;
degistirildikten sonra muslu.dev / muslu.org / djangoturkiye.com dahil hepsi
kontrol edildi, saglikli. Yedek: `/root/nginx.conf.yedek.*`.
HEAD istekleri artik 200 donuyor — `main.py` icinde router'lar mount edildikten
sonra tek gecisle GET route'larina HEAD ekleniyor (FastAPI `APIRoute` bunu
Starlette'in aksine kendiliginden yapmaz).

**Acik kalan isler:**

1. **Uyari: `git remote` URL'sinde GitHub PAT gomulu.** `.mcp.json` (sunucu root
   parolasi icerir) bir ara yanlislikla index'e alinmisti; unstage edildi ve gecmise
   sizmadi (HEAD'deki `ilk.txt` bostu). Commit oncesi `git diff --cached` ile bak.

2. **Ilk yazi yayinda:** "Alphacam'de Ilk VBA Makronuz" (id=1, 5 etiket, gorseli
   `static/img/blog/alphacam-makro-akisi.svg`). Yazidaki Alphacam API cekirdegi
   (`App`, `App.ActiveDrawing`, `Drw.RunQuery`, `App.LicomdatPath`) web
   kaynaklarindan dogrulandi; **geometri olusturma / operasyon ekleme imzalari
   dogrulanamadi**, o yuzden yaziya konmadi — okuyucu Object Browser'a
   yonlendiriliyor. Gokhan kendi kurulumunda teyit edince genisletilebilir.

3. **Panel erisimi:** kullanici adi `gokhan`. Parola sunucuda
   **`/opt/gokhancoskun/.panel-parola`** (mod 600). Eski `.ilk-parola` dosyasi
   rotasyonda silindi.

**2026-08-03 sir rotasyonu yapildi** (`scripts/anahtar_rotasyonu.py`):
FERNET_KEY, JWT_SECRET, PostgreSQL rol parolasi (40 hane) ve panel parolasi
(28 hane) yenilendi. Kritik nokta: FERNET_KEY once degistirilseydi DB'deki
sifreli parolalar cozulemez olurdu — betik once eski anahtarla cozup yeni
anahtarla yeniden sifreliyor, rol parolasini **ondan sonra** degistiriyor.
API tokenlari etkilenmez (SHA-256 ozeti, anahtarlara bagli degil).
Rotasyon sonrasi dogrulandi: eski parola reddediliyor, yeni parola ile giris
ve tum panel sayfalari 200, iletisim formu (bot-koruma token'i JWT_SECRET ile
imzalanir) calisiyor, public sayfalar 200.
Yedekler: `/root/gokhancoskun-yedek-20260803-150853/` (tam DB dump + eski .env)
ve `/opt/gokhancoskun/.env.env.yedek.20260803-151750`.

Ilgili: [[ssh-mcp-takilmasi]]
