#!/usr/bin/env bash
# ==================================================================
# panel.gokhancoskun.com icin Let's Encrypt sertifikasi alir ve
# nginx'i gecici apex sertifikasindan kendi sertifikasina gecirir.
#
# ON KOSUL: panel.gokhancoskun.com A kaydi bu sunucuya (185.122.200.36)
# isaret etmeli. Betik once bunu dogrular.
#
# Kullanim (sunucuda root olarak):
#     bash /opt/gokhancoskun/deploy/scripts/panel-ssl.sh
# ==================================================================
set -euo pipefail

APEX=gokhancoskun.com
PANEL=panel.gokhancoskun.com
EPOSTA=${CERTBOT_EPOSTA:-info@gokhancoskun.com}
NGINX_CONF=/etc/nginx/sites-available/$APEX.conf

bilgi() { printf '\033[32m==>\033[0m %s\n' "$*"; }
uyari() { printf '\033[33m!!!\033[0m %s\n' "$*"; }
hata()  { printf '\033[31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || hata "Bu betik root olarak calistirilmali."

# ------------------------------------------------------------------
# 1) DNS dogrulamasi
# ------------------------------------------------------------------
bilgi "DNS kontrol ediliyor: $PANEL"
SUNUCU_IP=$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
PANEL_IP=$(dig +short "$PANEL" A | tail -1)

if [[ -z $PANEL_IP ]]; then
    hata "$PANEL icin A kaydi bulunamadi.
    Alan adi kayit panelinizde (orderbox-dns.com) su kaydi olusturun:
        Tip: A    Ad: panel    Deger: $SUNUCU_IP    TTL: 300
    Kayit yayildiktan sonra bu betigi tekrar calistirin."
fi

if [[ $PANEL_IP != "$SUNUCU_IP" ]]; then
    hata "$PANEL -> $PANEL_IP, bu sunucu ise $SUNUCU_IP.
    A kaydini duzeltip DNS yayilmasini bekleyin."
fi
bilgi "DNS dogru: $PANEL -> $PANEL_IP"

# ------------------------------------------------------------------
# 2) HTTP-01 dogrulama yolu erisilebilir mi
# ------------------------------------------------------------------
mkdir -p /var/www/certbot/.well-known/acme-challenge
DENEME=$(openssl rand -hex 8)
echo "$DENEME" > "/var/www/certbot/.well-known/acme-challenge/$DENEME"
SONUC=$(curl -fsS --max-time 15 "http://$PANEL/.well-known/acme-challenge/$DENEME" 2>/dev/null || echo "")
rm -f "/var/www/certbot/.well-known/acme-challenge/$DENEME"

[[ $SONUC == "$DENEME" ]] || hata "ACME dogrulama yolu erisilemiyor.
    http://$PANEL/.well-known/acme-challenge/ 80 portundan servis edilmeli.
    nginx calisiyor mu, 80 portu acik mi kontrol edin."
bilgi "ACME dogrulama yolu erisilebilir"

# ------------------------------------------------------------------
# 3) Sertifika
# ------------------------------------------------------------------
if certbot certificates --cert-name "$PANEL" 2>/dev/null | grep -q "Certificate Name: $PANEL"; then
    bilgi "Sertifika zaten var — yenileniyor"
    certbot renew --cert-name "$PANEL" --quiet || uyari "Yenileme gerekmedi"
else
    bilgi "Sertifika aliniyor: $PANEL"
    certbot certonly \
        --webroot -w /var/www/certbot \
        -d "$PANEL" \
        --cert-name "$PANEL" \
        --key-type ecdsa \
        --email "$EPOSTA" \
        --agree-tos --no-eff-email --non-interactive
fi

[[ -f /etc/letsencrypt/live/$PANEL/fullchain.pem ]] || hata "Sertifika dosyasi olusmadi"
bilgi "Sertifika hazir"

# ------------------------------------------------------------------
# 4) nginx'i kendi sertifikasina gecir
# ------------------------------------------------------------------
bilgi "nginx panel blogu guncelleniyor"
cp "$NGINX_CONF" "$NGINX_CONF.yedek.$(date +%Y%m%d%H%M%S)"

# Panel server blogundaki sertifika yollarini duzelt.
# Yalnizca `server_name panel.…` blogundaki satirlar hedeflenir.
python3 - "$NGINX_CONF" "$APEX" "$PANEL" <<'PYTHON'
import re
import sys

yol, apex, panel = sys.argv[1], sys.argv[2], sys.argv[3]
metin = open(yol, encoding="utf-8").read()

# server_name panel.… iceren blogu bul ve icindeki apex sertifika yolunu degistir
def blok_duzelt(eslesme: re.Match) -> str:
    blok = eslesme.group(0)
    if f"server_name {panel};" not in blok:
        return blok
    return blok.replace(
        f"/etc/letsencrypt/live/{apex}/", f"/etc/letsencrypt/live/{panel}/"
    )

yeni = re.sub(r"server\s*\{(?:[^{}]|\{[^{}]*\})*\}", blok_duzelt, metin)
open(yol, "w", encoding="utf-8").write(yeni)
print("nginx yapilandirmasi guncellendi")
PYTHON

if nginx -t 2>&1 | grep -q 'test is successful'; then
    systemctl reload nginx
    bilgi "nginx yeniden yuklendi"
else
    nginx -t
    hata "nginx yapilandirmasi gecersiz — yedekten geri alin"
fi

# ------------------------------------------------------------------
# 5) Dogrulama
# ------------------------------------------------------------------
echo
bilgi "Dogrulama"
echo "--- TLS ---"
echo | openssl s_client -connect "$PANEL:443" -servername "$PANEL" 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates 2>/dev/null || uyari "TLS bilgisi alinamadi"

echo "--- HTTP/2 ---"
curl -sSI "https://$PANEL/giris" | head -1

echo "--- HTTP/3 ---"
curl -ksI --http3 "https://$PANEL/giris" 2>/dev/null | head -1 || uyari "curl HTTP/3 desteklemiyor olabilir"

echo "--- Basliklar ---"
curl -sSI "https://$PANEL/giris" | grep -iE 'alt-svc|strict-transport|x-robots|x-content-type|server:' || true

echo
bilgi "TAMAMLANDI — https://$PANEL"
