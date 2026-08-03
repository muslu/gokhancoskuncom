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

**Acik kalan isler:**

1. **Yerel degisiklikler HENUZ DEPLOY EDILMEDI.** Su isler yerelde bitti, sunucuda yok:
   ust/alt menu sirasi, `scrollbar-gutter` duzeltmesi, RSS kaldirma, iletisim formu
   e-posta + bot korumasi, anasayfadaki CNC animasyonu. Deploy icin dosya aktarimi
   gerekiyor — base64 ve yerel HTTP sunucusu izin siniflandiricisi tarafindan bloklandi;
   git uzerinden gitmek icin **commit + push onayi** bekleniyor.

2. **Panel SSL alinmadi.** `panel.gokhancoskun.com` hala apex sertifikasiyla sunuluyor
   (SAN'da yok → tarayici uyarir). DNS, certbot ve ACME webroot hazir; tek adim
   `deploy/scripts/panel-ssl.sh` — komut izin siniflandiricisi tarafindan bloklandi,
   kullanici onayi gerekiyor.

3. **`sitemap.xml` / `robots.txt` yanlis Content-Type donuyor** (`text/html`).
   Uygulama katmani **dogru** — ASGI seviyesinde olculdu, `robots.txt` →
   `text/plain; charset=utf-8`. Sorun ya nginx katmaninda (ortak
   `snippets/mailautoconfig.conf` supheli) ya da sunucudaki kodun eskiligi.
   Teshis: sunucuda `curl -sI http://127.0.0.1:8002/robots.txt`. (RSS kaldirildigi
   icin artik iki dosya.)

4. **`Server` header `musluyuksektepe`** donuyor, global kural `muslu@makdos` diyor.
   Deger ortak nginx yapilandirmasindan geliyor — degistirmek **diger siteleri de**
   etkiler, once kullaniciya sor.

5. **Yerel kod hic commit edilmedi.** `.mcp.json` (icinde sunucu root parolasi)
   yanlislikla index'e alinmisti; 2026-08-03'te unstage edildi, gecmise sizmadi
   (HEAD'deki `ilk.txt` bostu). Commit oncesi `git diff --cached` ile bir daha bak.
   Uyari: `git remote` URL'sinde GitHub PAT gomulu.

6. **Sitede hic icerik yok** — yayinlanmis yazi ve etiket sifir.

Ilgili: [[ssh-mcp-takilmasi]]
