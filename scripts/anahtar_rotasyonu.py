"""Uretim sirlarini yeniler: FERNET_KEY, JWT_SECRET, PostgreSQL ve panel parolasi.

Neden tek betik: bu dort deger birbirine baglidir ve **sirasi onemlidir.**
Elle yapildiginda en sik hata `FERNET_KEY`'i once degistirip veritabanindaki
sifreli parolalari cozulemez birakmaktir.

Ne yapar (bu sirayla):
  1. Yeni degerleri uretir.
  2. `users.password_enc` alanlarini ESKI anahtarla cozup YENI anahtarla
     yeniden sifreler — hicbir parola kaybolmaz.
  3. Panel kullanicisina yeni bir parola atar.
  4. PostgreSQL rolunun parolasini degistirir.
  5. `.env`'i gunceller (once yedekler).

Calistirma (sunucuda, proje kokunde):
    ./venv/bin/python scripts/anahtar_rotasyonu.py

Sonrasinda servisi yeniden baslatmak gerekir. Betik bunu KENDISI yapmaz —
yeniden baslatma zamanini cagiran belirlesin diye.

Etkiler:
  * Acik panel oturumlari duser (JWT_SECRET degisti) → tekrar giris gerekir.
  * Acik iletisim formlari gecersizlesir (bot-koruma token'i JWT_SECRET ile
    imzalanir) → ziyaretci sayfayi yenileyince duzelir.
  * API tokenlari ETKILENMEZ: SHA-256 ozetiyle saklanirlar, bu anahtarlara
    bagli degillerdir.
"""

import asyncio
import re
import secrets
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

KOK = Path(__file__).resolve().parent.parent
ENV = KOK / ".env"

# Elle girilebilir alfabe: birbirine benzeyen karakterler (0/O, 1/l/I) yok.
# Parola panele elle yazilacagi icin okunabilirlik guvenlikten odun degil —
# uzunluk zaten entropiyi fazlasiyla karsiliyor.
ALFABE = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def parola_uret(uzunluk: int) -> str:
    """Kriptografik olarak guvenli, elle girilebilir parola uretir."""
    return "".join(secrets.choice(ALFABE) for _ in range(uzunluk))


def env_oku() -> dict[str, str]:
    """`.env` dosyasini anahtar/deger sozluguna cevirir."""
    degerler: dict[str, str] = {}
    for satir in ENV.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, _, deger = satir.partition("=")
        degerler[anahtar.strip()] = deger.strip().strip('"')
    return degerler


def env_yaz(yeni: dict[str, str]) -> Path:
    """`.env`'i yedekleyip verilen anahtarlari gunceller. Yedek yolunu dondurur."""
    yedek = ENV.with_suffix(f".env.yedek.{datetime.now():%Y%m%d-%H%M%S}")
    metin = ENV.read_text(encoding="utf-8")
    yedek.write_text(metin, encoding="utf-8")

    for anahtar, deger in yeni.items():
        desen = rf"^{re.escape(anahtar)}=.*$"
        if re.search(desen, metin, flags=re.MULTILINE):
            metin = re.sub(desen, f"{anahtar}={deger}", metin, flags=re.MULTILINE)
        else:
            metin += f"\n{anahtar}={deger}\n"

    ENV.write_text(metin, encoding="utf-8")
    return yedek


async def _veritabanini_guncelle(
    eski: dict[str, str],
    eski_fernet: Fernet,
    yeni_fernet: Fernet,
    yeni_panel_parolasi: str,
    yeni_db_parolasi: str,
) -> None:
    """Parolalari yeni anahtarla yeniden sifreler, sonra rol parolasini degistirir.

    Sira kritik: rol parolasi once degistirilse bagli oturum kopar ve yeniden
    sifreleme yarim kalirdi.
    """
    import asyncpg

    baglanti = await asyncpg.connect(
        host=eski.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(eski.get("POSTGRES_PORT", "5432")),
        database=eski["POSTGRES_DB"],
        user=eski["POSTGRES_USER"],
        password=eski["POSTGRES_PASSWORD"],
    )
    try:
        async with baglanti.transaction():
            kayitlar = await baglanti.fetch(
                "SELECT id, username, password_enc FROM users ORDER BY id"
            )
            print(f"  {len(kayitlar)} kullanici bulundu")

            yonetici_adi = eski.get("ADMIN_USERNAME", "")
            for k in kayitlar:
                if k["username"] == yonetici_adi:
                    duz = yeni_panel_parolasi
                    print(f"  {k['username']}: YENI parola atandi")
                else:
                    # Eski anahtarla cozup yeni anahtarla sifrelemek zorunlu;
                    # bu adim atlanirsa parola geri donusu olmadan kaybolur.
                    duz = eski_fernet.decrypt(k["password_enc"].encode()).decode()
                    print(f"  {k['username']}: parola korundu, yeniden sifrelendi")

                await baglanti.execute(
                    "UPDATE users SET password_enc = $1, updated_at = now() WHERE id = $2",
                    yeni_fernet.encrypt(duz.encode()).decode(),
                    k["id"],
                )

        # ALTER ROLE bir DDL ifadesidir, bind parametresi kabul etmez; deger
        # literal olarak gomulur. Uretilen alfabe yalnizca harf/rakam icerdigi
        # icin kacis sorunu yok — assert bunu garanti eder.
        if not yeni_db_parolasi.isalnum():
            raise ValueError("DB parolasi alfanumerik olmali (SQL literal olarak gomuluyor)")
        rol = eski["POSTGRES_USER"].replace('"', '""')
        await baglanti.execute(f'ALTER ROLE "{rol}" WITH PASSWORD \'{yeni_db_parolasi}\'')
        print("  veritabani: parolalar yeniden sifrelendi, rol parolasi degisti")
    finally:
        await baglanti.close()


def main() -> int:
    """Rotasyonu calistirir."""
    if not ENV.exists():
        print(f"HATA: {ENV} bulunamadi", file=sys.stderr)
        return 1

    eski = env_oku()
    eski_fernet_anahtari = eski.get("FERNET_KEY", "")
    if not eski_fernet_anahtari:
        print("HATA: .env icinde FERNET_KEY yok — cozulecek parolalar kaybolur.",
              file=sys.stderr)
        return 1

    # --- 1) Yeni degerler ---------------------------------------------
    yeni_fernet_anahtari = Fernet.generate_key().decode()
    yeni_jwt = secrets.token_urlsafe(64)
    yeni_db_parolasi = parola_uret(40)
    yeni_panel_parolasi = parola_uret(28)

    eski_fernet = Fernet(eski_fernet_anahtari.encode())
    yeni_fernet = Fernet(yeni_fernet_anahtari.encode())

    # --- 2) Veritabani (ESKI parola hala gecerli) ----------------------
    asyncio.run(
        _veritabanini_guncelle(
            eski, eski_fernet, yeni_fernet, yeni_panel_parolasi, yeni_db_parolasi
        )
    )

    # --- 4) .env -------------------------------------------------------
    yedek = env_yaz({
        "FERNET_KEY": yeni_fernet_anahtari,
        "JWT_SECRET": yeni_jwt,
        "POSTGRES_PASSWORD": yeni_db_parolasi,
        "ADMIN_PASSWORD": yeni_panel_parolasi,
    })
    print(f"  .env guncellendi (yedek: {yedek.name})")

    # --- 5) Yeni panel parolasini korumali dosyaya yaz -----------------
    parola_dosyasi = KOK / ".panel-parola"
    parola_dosyasi.write_text(
        f"kullanici: {eski.get('ADMIN_USERNAME', '?')}\nparola  : {yeni_panel_parolasi}\n",
        encoding="utf-8",
    )
    parola_dosyasi.chmod(0o600)

    # Artik gecersiz olan ilk kurulum parolasi ortalikta durmasin
    ilk = KOK / ".ilk-parola"
    if ilk.exists():
        ilk.unlink()
        print("  eski .ilk-parola dosyasi silindi")

    print("\nTAMAM. Simdi servisi yeniden baslatin:")
    print("    systemctl restart gokhancoskun.service")
    print(f"Yeni panel parolasi: {parola_dosyasi}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
