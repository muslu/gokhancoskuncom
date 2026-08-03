#!/usr/bin/env bash
# ==================================================================
# gokhancoskun.com — sunucu kurulum / guncelleme betigi (idempotent)
#
# Kullanim (sunucuda root olarak):
#     bash /opt/gokhancoskun/deploy/scripts/deploy.sh
#
# Docker YOK — bare-metal systemd. Paket yoneticisi: nala.
# ==================================================================
set -euo pipefail

PROJE=gokhancoskun
KOK=/opt/$PROJE
SERVIS=$PROJE.service
PY=python3.12
DB_AD=gokhancoskundb
DB_KULLANICI=gokhancoskun
APEX=gokhancoskun.com
PANEL=panel.gokhancoskun.com

bilgi() { printf '\033[32m==>\033[0m %s\n' "$*"; }
uyari() { printf '\033[33m!!!\033[0m %s\n' "$*"; }
hata()  { printf '\033[31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || hata "Bu betik root olarak calistirilmali."
[[ -d $KOK ]] || hata "$KOK bulunamadi — once dosyalari kopyalayin."

# ------------------------------------------------------------------
# 1) Sistem paketleri
# ------------------------------------------------------------------
bilgi "Sistem paketleri kontrol ediliyor"
command -v nala >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq nala; }

EKSIK=()
command -v $PY            >/dev/null 2>&1 || EKSIK+=("$PY" "$PY-venv" "$PY-dev")
dpkg -s valkey-server     >/dev/null 2>&1 || EKSIK+=(valkey-server)
dpkg -s libpq-dev         >/dev/null 2>&1 || EKSIK+=(libpq-dev)
dpkg -s build-essential   >/dev/null 2>&1 || EKSIK+=(build-essential)

if [[ ${#EKSIK[@]} -gt 0 ]]; then
    bilgi "Kurulacak paketler: ${EKSIK[*]}"
    nala install -y "${EKSIK[@]}"
else
    bilgi "Tum paketler zaten kurulu"
fi

# ------------------------------------------------------------------
# 2) Valkey — yalnizca localhost, TTL zorunlu politikasi
# ------------------------------------------------------------------
bilgi "Valkey yapilandiriliyor"
VALKEY_CONF=/etc/valkey/valkey.conf
if [[ -f $VALKEY_CONF ]]; then
    sed -i 's/^# *maxmemory .*/maxmemory 256mb/;  s/^maxmemory .*/maxmemory 256mb/' "$VALKEY_CONF"
    grep -q '^maxmemory ' "$VALKEY_CONF" || echo 'maxmemory 256mb' >> "$VALKEY_CONF"
    sed -i 's/^# *maxmemory-policy .*/maxmemory-policy allkeys-lru/; s/^maxmemory-policy .*/maxmemory-policy allkeys-lru/' "$VALKEY_CONF"
    grep -q '^maxmemory-policy ' "$VALKEY_CONF" || echo 'maxmemory-policy allkeys-lru' >> "$VALKEY_CONF"
    grep -qE '^bind 127\.0\.0\.1' "$VALKEY_CONF" || sed -i 's/^bind .*/bind 127.0.0.1 -::1/' "$VALKEY_CONF"
fi
systemctl enable --now valkey-server >/dev/null 2>&1 || systemctl restart valkey-server
systemctl is-active --quiet valkey-server && bilgi "Valkey calisiyor" || uyari "Valkey baslatilamadi"

# ------------------------------------------------------------------
# 3) PostgreSQL veritabani + kullanici
# ------------------------------------------------------------------
bilgi "PostgreSQL hazirlaniyor"
systemctl is-active --quiet postgresql || systemctl start postgresql

if [[ -f $KOK/.env ]]; then
    DB_PAROLA=$(grep -E '^POSTGRES_PASSWORD=' "$KOK/.env" | cut -d= -f2-)
fi
DB_PAROLA=${DB_PAROLA:-$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)}

VAR_MI=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='$DB_KULLANICI'\"")
if [[ $VAR_MI == 1 ]]; then
    su - postgres -c "psql -qc \"ALTER ROLE $DB_KULLANICI WITH LOGIN PASSWORD '$DB_PAROLA'\"" >/dev/null
    bilgi "DB kullanicisi guncellendi: $DB_KULLANICI"
else
    su - postgres -c "psql -qc \"CREATE ROLE $DB_KULLANICI WITH LOGIN PASSWORD '$DB_PAROLA'\"" >/dev/null
    bilgi "DB kullanicisi olusturuldu: $DB_KULLANICI"
fi

DB_VAR=$(su - postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='$DB_AD'\"")
if [[ $DB_VAR != 1 ]]; then
    su - postgres -c "createdb -O $DB_KULLANICI $DB_AD"
    bilgi "Veritabani olusturuldu: $DB_AD"
fi
# Eklentiler yalnizca superuser ile kurulabilir
su - postgres -c "psql -q -d $DB_AD -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS unaccent;'" >/dev/null
su - postgres -c "psql -q -d $DB_AD -c 'GRANT ALL ON SCHEMA public TO $DB_KULLANICI'" >/dev/null

# ------------------------------------------------------------------
# 4) .env — yoksa uretilir, varsa korunur
# ------------------------------------------------------------------
if [[ ! -f $KOK/.env ]]; then
    bilgi ".env uretiliyor"
    FERNET=$($PY -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
             || echo "KURULUM_SONRASI_URETILECEK")
    JWT=$(openssl rand -base64 48 | tr -d '\n')
    ADMIN_PAROLA=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)

    cat > "$KOK/.env" <<EOF
APP_NAME="Gökhan Coşkun"
APP_ENV=production
DEBUG=false
SITE_URL=https://$APEX
PANEL_URL=https://$PANEL
HOST=127.0.0.1
PORT=8002

POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=$DB_AD
POSTGRES_USER=$DB_KULLANICI
POSTGRES_PASSWORD=$DB_PAROLA
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=5
PGBOUNCER_HOST=
PGBOUNCER_PORT=

VALKEY_HOST=127.0.0.1
VALKEY_PORT=6379
VALKEY_DB=3
VALKEY_PASSWORD=
CACHE_DEFAULT_TTL=300

FERNET_KEY=$FERNET
JWT_SECRET=$JWT
JWT_ALGORITHM=HS256
TOKEN_EXPIRE_MINUTES=120
SESSION_COOKIE_NAME=gc_session
COOKIE_SECURE=true

RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
LOGIN_RATE_LIMIT_REQUESTS=5
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300

MEDIA_ROOT=$KOK/media
MEDIA_URL=/media
MAX_UPLOAD_MB=8

GOOGLE_SITE_VERIFICATION=
GA4_MEASUREMENT_ID=

SMTP_HOST=127.0.0.1
SMTP_PORT=25
SMTP_USER=
SMTP_PASSWORD=
SMTP_STARTTLS=false
SMTP_TIMEOUT=15
MAIL_FROM=siteform@$APEX
MAIL_FROM_NAME="$APEX iletişim formu"
MAIL_TO=gokhancoskun1983@gmail.com

FORM_MIN_SECONDS=3
FORM_MAX_SECONDS=3600

ADMIN_USERNAME=gokhan
ADMIN_EMAIL=info@$APEX
ADMIN_PASSWORD=$ADMIN_PAROLA
EOF
    echo "$ADMIN_PAROLA" > "$KOK/.ilk-parola"
    chmod 600 "$KOK/.ilk-parola"
    uyari "Ilk yonetici parolasi: $KOK/.ilk-parola (giris sonrasi degistirip silin)"
else
    bilgi ".env mevcut — korunuyor"
    # DB parolasi degismis olabilir, senkronla
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DB_PAROLA|" "$KOK/.env"
fi
chmod 640 "$KOK/.env"

# ------------------------------------------------------------------
# 5) Python sanal ortami
# ------------------------------------------------------------------
bilgi "Python ortami hazirlaniyor"
[[ -d $KOK/venv ]] || $PY -m venv "$KOK/venv"
"$KOK/venv/bin/pip" install --quiet --upgrade pip setuptools wheel
"$KOK/venv/bin/pip" install --quiet -r "$KOK/requirements.txt"
bilgi "Bagimliliklar kuruldu ($("$KOK/venv/bin/python" --version))"

# FERNET_KEY yer tutucu kaldiysa simdi uret
if grep -q '^FERNET_KEY=KURULUM_SONRASI_URETILECEK' "$KOK/.env"; then
    YENI_FERNET=$("$KOK/venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    sed -i "s|^FERNET_KEY=.*|FERNET_KEY=$YENI_FERNET|" "$KOK/.env"
    bilgi "FERNET_KEY uretildi"
fi

# ------------------------------------------------------------------
# 6) Izinler
# ------------------------------------------------------------------
mkdir -p "$KOK/media"
chown -R www-data:www-data "$KOK"
chmod 750 "$KOK"
find "$KOK" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# ------------------------------------------------------------------
# 7) systemd
# ------------------------------------------------------------------
bilgi "systemd birimi kuruluyor"
install -m 644 "$KOK/deploy/systemd/$SERVIS" "/etc/systemd/system/$SERVIS"
systemctl daemon-reload
systemctl enable "$SERVIS" >/dev/null 2>&1 || true
systemctl restart "$SERVIS"
sleep 3

if systemctl is-active --quiet "$SERVIS"; then
    bilgi "Servis calisiyor: $SERVIS"
else
    journalctl -u "$SERVIS" -n 40 --no-pager
    hata "Servis baslatilamadi"
fi

# ------------------------------------------------------------------
# 8) nginx
# ------------------------------------------------------------------
bilgi "nginx yapilandiriliyor"
NGINX_HEDEF=/etc/nginx/sites-available/$APEX.conf
cp "$KOK/deploy/nginx/$APEX.conf" "$NGINX_HEDEF"

# Panel sertifikasi henuz yoksa gecici olarak apex sertifikasini kullan
if [[ ! -f /etc/letsencrypt/live/$PANEL/fullchain.pem ]]; then
    uyari "Panel sertifikasi yok — gecici olarak apex sertifikasi kullaniliyor"
    sed -i "s|/etc/letsencrypt/live/$PANEL/|/etc/letsencrypt/live/$APEX/|g" "$NGINX_HEDEF"
fi

ln -sfn "$NGINX_HEDEF" "/etc/nginx/sites-enabled/$APEX.conf"

if nginx -t 2>&1 | grep -q 'test is successful'; then
    systemctl reload nginx
    bilgi "nginx yeniden yuklendi"
else
    nginx -t
    hata "nginx yapilandirmasi gecersiz"
fi

# UDP 443 — HTTP/3
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'; then
    ufw allow 443/udp >/dev/null 2>&1 || true
    bilgi "ufw: 443/udp acildi (HTTP/3)"
fi

# ------------------------------------------------------------------
# 9) Dogrulama
# ------------------------------------------------------------------
bilgi "Saglik kontrolu"
sleep 1
if curl -fsS --max-time 10 http://127.0.0.1:8002/saglik; then
    echo
    bilgi "KURULUM TAMAMLANDI"
else
    echo
    journalctl -u "$SERVIS" -n 30 --no-pager
    hata "Saglik kontrolu basarisiz"
fi

echo
echo "  Site  : https://$APEX"
echo "  Panel : https://$PANEL"
echo "  Servis: systemctl status $SERVIS"
echo "  Gunluk: journalctl -u $SERVIS -f"
[[ -f $KOK/.ilk-parola ]] && echo "  Parola: cat $KOK/.ilk-parola"
echo
