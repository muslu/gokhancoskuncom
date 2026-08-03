"""SMTP uzerinden e-posta gonderimi — iletisim formu bildirimleri.

Sunucuda Postfix zaten calistigi icin varsayilan hedef `127.0.0.1:25`;
kimlik dogrulama gerekmez, teslimati Postfix ustlenir. Harici bir SMTP
saglayicisi kullanilacaksa `.env` icinde SMTP_USER / SMTP_PASSWORD doldurulur
ve SMTP_STARTTLS acilir.

Gonderim **bloklayicidir**; endpoint'ten dogrudan cagrilmaz, her zaman
`BackgroundTasks` uzerinden calistirilir — SMTP yavaslarsa ziyaretci beklemez.
"""

import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import make_msgid

from src.colorlogger import logger as lg
from src.config import settings


def _adres(eposta: str, gorunen_ad: str = "") -> Address:
    """`ad@alan` dizesini, gorunen adi olan bir `Address` nesnesine cevirir."""
    kullanici, _, alan = eposta.partition("@")
    return Address(display_name=gorunen_ad, username=kullanici, domain=alan)


def _gonder(ileti: EmailMessage) -> None:
    """Hazir bir iletiyi SMTP'ye teslim eder. Hata durumunda istisna firlatir."""
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
    ) as baglanti:
        if settings.smtp_starttls:
            baglanti.starttls()
        if settings.smtp_user:
            baglanti.login(settings.smtp_user, settings.smtp_password)
        baglanti.send_message(ileti)


def iletisim_yaniti_gonder(
    *,
    alici_ad: str,
    alici_eposta: str,
    konu: str | None,
    yanit: str,
    orijinal_mesaj: str,
) -> None:
    """Panelden yazilan yaniti ziyaretciye e-posta olarak gonderir.

    Args:
        alici_ad: Mesaji gonderen kisinin adi.
        alici_eposta: Yanitin gidecegi adres.
        konu: Orijinal mesajin konusu; basina "Re: " eklenir.
        yanit: Panelde yazilan yanit metni.
        orijinal_mesaj: Yanitin altina alintilanacak ilk mesaj.

    Raises:
        smtplib.SMTPException | OSError: Gonderim basarisiz olursa. Bu fonksiyon
            **hatayi yutmaz** — iletisim formu bildiriminin aksine burada
            sonucu bekleyen bir kullanici var; panelde "gonderildi" yazip
            sessizce kaybolan bir yanit en kotu sonuctur.
    """
    ileti = EmailMessage()
    ileti["Subject"] = f"Re: {konu}" if konu else "Mesajınıza yanıt"
    ileti["From"] = _adres(settings.mail_from, settings.app_name)
    ileti["To"] = _adres(alici_eposta, alici_ad)
    # Ziyaretci yanitlarsa dogrudan site sahibinin kutusuna dussun.
    ileti["Reply-To"] = _adres(settings.mail_to)
    ileti["Message-ID"] = make_msgid(domain=settings.mail_from.partition("@")[2])

    alinti = "\n".join(f"> {satir}" for satir in orijinal_mesaj.splitlines())
    ileti.set_content(
        f"""Merhaba {alici_ad},

{yanit}

--
{settings.app_name}
{settings.site_url}

------------------------------------------------------------
Gönderdiğiniz mesaj:

{alinti}
"""
    )

    _gonder(ileti)
    lg.info("Iletisim yaniti gonderildi → %s", alici_eposta)


def iletisim_bildirimi_gonder(
    *,
    ad: str,
    eposta: str,
    konu: str | None,
    mesaj: str,
    ip: str,
    mesaj_id: int,
) -> bool:
    """Iletisim formu mesajini site sahibine e-posta ile iletir.

    Args:
        ad: Gonderenin adi.
        eposta: Gonderenin e-posta adresi (Reply-To olarak kullanilir).
        konu: Form konusu; bos olabilir.
        mesaj: Mesaj govdesi.
        ip: Gonderimin geldigi IP adresi.
        mesaj_id: `contact_messages` tablosundaki kayit kimligi.

    Returns:
        Gonderim basariliysa True, aksi halde False. Bu fonksiyon **istisna
        firlatmaz** — arka plan gorevinden cagrildigi icin hatayi loglar ve
        doner; mesaj zaten veritabanina yazilmis durumdadir, e-posta yalnizca
        bildirim katmanidir.
    """
    ileti = EmailMessage()
    ileti["Subject"] = f"[İletişim formu] {konu or 'Yeni mesaj'}"
    ileti["From"] = _adres(settings.mail_from, settings.mail_from_name)
    ileti["To"] = _adres(settings.mail_to)
    # Yanitla dendiginde ziyaretcinin adresine gitsin; From site adresi kalir
    # (aksi halde SPF/DKIM uyusmaz ve mesaj spam'e duser).
    ileti["Reply-To"] = _adres(eposta, ad)
    ileti["Message-ID"] = make_msgid(domain=settings.mail_from.partition("@")[2])
    ileti["X-Site-Mesaj-Id"] = str(mesaj_id)

    ileti.set_content(
        f"""gokhancoskun.com iletişim formundan yeni bir mesaj alındı.

Ad      : {ad}
E-posta : {eposta}
Konu    : {konu or '(belirtilmedi)'}
IP      : {ip}
Kayıt   : #{mesaj_id}

--- Mesaj ---
{mesaj}
"""
    )

    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
        ) as baglanti:
            if settings.smtp_starttls:
                baglanti.starttls()
            if settings.smtp_user:
                baglanti.login(settings.smtp_user, settings.smtp_password)
            baglanti.send_message(ileti)
    except (smtplib.SMTPException, OSError) as exc:
        lg.error(
            "Iletisim bildirimi gonderilemedi (kayit #%s): %s: %s",
            mesaj_id, type(exc).__name__, exc,
        )
        return False

    lg.info("Iletisim bildirimi gonderildi: kayit #%s → %s", mesaj_id, settings.mail_to)
    return True
