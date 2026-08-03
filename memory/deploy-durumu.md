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

**Acik kalan isler:**

1. **HEAD istekleri tum sitede 405 donuyor** (GET'ler sorunsuz).
   FastAPI'nin `APIRoute`'u — Starlette'in `Route`'unun aksine — `@router.get`
   ile tanimlanan yollara **HEAD eklemez**; `main.app.routes` uzerinde dogrulandi:
   `/` → `['GET']`. Etkisi: HEAD kullanan uptime monitorleri, link denetleyicileri
   ve bazi crawler'lar 405 alir.
   Duzeltme secenekleri: ilgili yollari `@router.api_route(..., methods=["GET","HEAD"])`
   ile tanimlamak (8 route) veya tek bir middleware'de HEAD'i GET'e cevirmek
   (govde/Content-Length davranisi dikkat ister). Kapsam disi oldugu icin yapilmadi.

   **ONCEKI TESHIS YANLISTI, DUZELTILDI:** "sitemap/robots yanlis Content-Type
   donuyor" diye kaydedilen bulgu gercek degildi — `curl -I` HEAD gonderdigi icin
   405 hata sayfasinin `text/html` tipi olculmustu. Gercek GET yanitlari **dogru**:
   `robots.txt` → `text/plain; charset=utf-8`, `sitemap.xml` → `application/xml; charset=utf-8`.
   nginx bu konuda tamamen suclu degil. Ders: Content-Type olcerken `curl -I` degil
   `curl -s -o /dev/null -w '%{content_type}'` kullan.

2. **`Server` header `musluyuksektepe`** donuyor, global kural `muslu@makdos` diyor.
   Deger ortak nginx yapilandirmasindan geliyor — degistirmek **diger siteleri de**
   etkiler, once kullaniciya sor.

3. **Uyari: `git remote` URL'sinde GitHub PAT gomulu.** `.mcp.json` (sunucu root
   parolasi icerir) bir ara yanlislikla index'e alinmisti; unstage edildi ve gecmise
   sizmadi (HEAD'deki `ilk.txt` bostu). Commit oncesi `git diff --cached` ile bak.

4. **Ilk yazi yayinda:** "Alphacam'de Ilk VBA Makronuz" (id=1, 5 etiket, gorseli
   `static/img/blog/alphacam-makro-akisi.svg`). Yazidaki Alphacam API cekirdegi
   (`App`, `App.ActiveDrawing`, `Drw.RunQuery`, `App.LicomdatPath`) web
   kaynaklarindan dogrulandi; **geometri olusturma / operasyon ekleme imzalari
   dogrulanamadi**, o yuzden yaziya konmadi — okuyucu Object Browser'a
   yonlendiriliyor. Gokhan kendi kurulumunda teyit edince genisletilebilir.

5. **Panel erisimi:** kullanici adi `gokhan`. Parola sunucuda
   `/opt/gokhancoskun/.ilk-parola` dosyasinda; ayrica DB'de Fernet ile geri
   cozulebilir sekilde duruyor (`decrypt_password`). `last_login_at` uzun sure
   bos kaldi — parola degistirilince o dosya silinmeli.

Ilgili: [[ssh-mcp-takilmasi]]
