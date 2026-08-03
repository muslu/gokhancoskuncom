"""Iletisim formu icin captcha'siz bot korumasi.

Neden reCAPTCHA degil:
  * Harici script gerektirir → CSP'de `script-src`/`frame-src` gevsetilmesi gerekir,
    oysa sitenin CSP'si su an tek bir inline script hash'i disinda tamamen kapali.
  * Google'a ucuncu taraf istegi gider (KVKK/gizlilik yuku).
  * Gorsel/isitsel bulmacalar erisilebilirlik acisindan sorunlu (WCAG).

Bunun yerine uc katman birlikte calisir:
  1. Honeypot alani (`website`) — sablonda gizli, dolduran bot'tur.
  2. Bu modul: formun **render edildigi ani** imzali bir token'a yazar, gonderimde
     gecen sureyi olcer. Insanin form doldurmasi saniyeler alir; otomatik gonderim
     ya aninda olur ya da eski bir sayfadan toplu yapilir — ikisi de elenir.
  3. Endpoint uzerindeki `@rate_limit` (5 istek / 10 dk).

Token JWT_SECRET ile imzalanir; istemci uretemez veya zaman damgasini degistiremez.
"""

from datetime import UTC, datetime

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.colorlogger import logger as lg
from src.config import settings

_TUZ = "iletisim-formu-v1"


class FormTokenHatasi(Exception):
    """Form token'i eksik, bozuk veya kabul edilebilir zaman araliginin disinda."""

    def __init__(self, kullanici_mesaji: str, kayit_nedeni: str) -> None:
        super().__init__(kayit_nedeni)
        self.kullanici_mesaji = kullanici_mesaji
        self.kayit_nedeni = kayit_nedeni


def _seri_lestirici() -> URLSafeTimedSerializer:
    """Token imzalayicisini dondurur (JWT_SECRET ile imzalar)."""
    return URLSafeTimedSerializer(settings.jwt_secret, salt=_TUZ)


def form_tokeni_uret() -> str:
    """Formun render edildigi ani imzalayan yeni bir token uretir."""
    return _seri_lestirici().dumps("iletisim")


def form_tokeni_dogrula(token: str) -> None:
    """Token'i dogrular; gecersizse `FormTokenHatasi` firlatir.

    Args:
        token: Formdaki gizli alandan gelen imzali token.

    Raises:
        FormTokenHatasi: Token yok, imza gecersiz, sure asilmis veya form
            insan icin imkansiz denecek kadar hizli gonderilmis.
    """
    if not token:
        raise FormTokenHatasi(
            "Form oturumu doğrulanamadı. Lütfen sayfayı yenileyip tekrar deneyin.",
            "token yok",
        )

    try:
        # return_timestamp: token'in uretildigi ani da geri alir, boylece
        # yalnizca ust siniri degil alt siniri da olcebiliriz.
        _, uretim_ani = _seri_lestirici().loads(
            token, max_age=settings.form_max_seconds, return_timestamp=True
        )
    except SignatureExpired as exc:
        raise FormTokenHatasi(
            "Form çok uzun süre açık kaldı. Lütfen sayfayı yenileyip tekrar deneyin.",
            "token suresi doldu",
        ) from exc
    except BadSignature as exc:
        raise FormTokenHatasi(
            "Form oturumu doğrulanamadı. Lütfen sayfayı yenileyip tekrar deneyin.",
            "token imzasi gecersiz",
        ) from exc

    gecen = (datetime.now(UTC) - uretim_ani).total_seconds()
    if gecen < settings.form_min_seconds:
        raise FormTokenHatasi(
            "Form beklenenden hızlı gönderildi. Lütfen tekrar deneyin.",
            f"form {gecen:.1f} sn'de gonderildi (alt sinir {settings.form_min_seconds})",
        )

    lg.debug("Iletisim formu token dogrulandi: %.1f sn", gecen)
