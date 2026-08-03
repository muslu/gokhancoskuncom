"""Kimlik dogrulama: panel icin JWT cookie oturumu, API icin Bearer token."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.colorlogger import logger
from src.config import settings
from src.models import repository as repo

_bearer = HTTPBearer(auto_error=False, description="API token (Bearer)")


# ------------------------------------------------------------------
# JWT — panel oturumu
# ------------------------------------------------------------------
def create_access_token(user: dict[str, Any]) -> str:
    """Kullanici icin imzali JWT uretir."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.token_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """JWT'yi cozer; gecersiz/suresi dolmussa None dondurur."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        logger.info("Oturum jetonunun suresi dolmus")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("Gecersiz oturum jetonu: %s", exc)
        return None


async def authenticate_cookie(request: Request) -> dict[str, Any] | None:
    """Cookie'deki oturumu cozer; yoksa None dondurur.

    Panel router'i bu fonksiyonu dogrudan cagirir (Depends yerine) — boylece
    oturumsuz istekte 401 yerine `/giris` sayfasina yonlendirme yapilabilir.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    return await repo.get_user_by_id(int(payload["sub"]))


# Public sayfalarda "oturum var mi" kontrolu icin okunakli takma ad
current_user_optional = authenticate_cookie


async def require_user(request: Request) -> dict[str, Any]:
    """Panel sayfalari icin oturum zorunlulugu (yoksa 401)."""
    user = await authenticate_cookie(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum açmanız gerekiyor",
            headers={"Location": "/giris"},
        )
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    """Yalnizca `admin` rolune izin verir."""
    if user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Bu işlem için yetkiniz yok"
        )
    return user


# ------------------------------------------------------------------
# Bearer token — API / MCP
# ------------------------------------------------------------------
async def require_api_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """API token'ini dogrular ve token kaydini dondurur."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token gerekli (Authorization: Bearer <token>)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = await repo.resolve_api_token(credentials.credentials)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Geçersiz veya süresi dolmuş API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def require_scope(scope: str):
    """Belirli bir kapsami zorunlu kilan bagimlilik uretir."""

    async def dependency(
        token: dict[str, Any] = Depends(require_api_token),
    ) -> dict[str, Any]:
        """Token kapsamlari arasinda istenen kapsam var mi kontrol eder."""
        scopes = {s.strip() for s in str(token["scopes"]).split(",")}
        if scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token bu işlem için yetkili değil (gerekli kapsam: {scope})",
            )
        return token

    return dependency
