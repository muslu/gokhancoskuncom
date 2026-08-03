"""Fernet simetrik sifreleme — parolalar geri donusumlu olarak saklanir.

Bu modul dogrudan router'lardan kullanilmaz; erisim `src/models/` katmani
uzerinden yapilir. `FERNET_KEY` degisirse mevcut parolalar cozulemez.
"""

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from src.colorlogger import logger
from src.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Tekil Fernet ornegi dondurur; anahtar gecersizse hata firlatir."""
    global _fernet
    if _fernet is None:
        if not settings.fernet_key:
            raise RuntimeError("FERNET_KEY .env icinde tanimli degil")
        try:
            _fernet = Fernet(settings.fernet_key.encode())
        except (ValueError, TypeError) as exc:
            logger.error("FERNET_KEY gecersiz: %s", exc)
            raise RuntimeError("FERNET_KEY gecersiz formatta") from exc
    return _fernet


def encrypt_password(plain: str) -> str:
    """Duz metin parolayi Fernet ile sifreler ve saklanabilir string dondurur."""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(stored: str) -> str:
    """Sifreli parolayi cozer; token gecersizse `InvalidToken` firlatir."""
    return _get_fernet().decrypt(stored.encode()).decode()


def verify_password(plain: str, stored: str) -> bool:
    """Duz metin parolayi sifreli deger ile sabit zamanli karsilastirir."""
    try:
        return hmac.compare_digest(decrypt_password(stored), plain)
    except InvalidToken:
        logger.warning("Parola dogrulamasi basarisiz: cozulemeyen token")
        return False


def generate_api_token() -> str:
    """MCP/API istemcileri icin URL-guvenli rastgele token uretir."""
    return f"gc_{secrets.token_urlsafe(40)}"


def hash_api_token(token: str) -> str:
    """API token'ini DB'de saklamak icin SHA-256 ozeti alir (geri donusumsuz)."""
    return hashlib.sha256(token.encode()).hexdigest()
