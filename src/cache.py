"""Valkey/Redis cache servisi.

Kurallar: her `set` isleminde TTL zorunlu, `KEYS *` yasak (SCAN kullanilir),
serialize `json` ile yapilir (pickle yasak).

Cache key semasi: `{kaynak}:{tip}:{id}` — ornek `post:detail:merhaba-dunya`.
"""

import json
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from src.colorlogger import logger
from src.config import settings


class CacheService:
    """Async Valkey istemcisi — JSON serialize + zorunlu TTL."""

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._available = False

    def connect(self) -> None:
        """Istemciyi olusturur (idempotent)."""
        if self._client is not None:
            return
        self._client = redis.Redis(
            host=settings.valkey_host,
            port=settings.valkey_port,
            db=settings.valkey_db,
            password=settings.valkey_password or None,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        self._available = True
        logger.info("Valkey istemcisi hazir (db=%s)", settings.valkey_db)

    async def disconnect(self) -> None:
        """Baglantiyi kapatir."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._available = False
            logger.info("Valkey baglantisi kapatildi")

    @property
    def available(self) -> bool:
        """Cache kullanilabilir durumda mi (dusunce hata degil, MISS kabul edilir)."""
        return self._available and self._client is not None

    async def get_json(self, key: str) -> Any | None:
        """Anahtari okur ve JSON cozer; yoksa/hata varsa None dondurur."""
        if not self.available:
            return None
        try:
            raw = await self._client.get(key)  # type: ignore[union-attr]
        except RedisError as exc:
            logger.warning("Cache okuma hatasi (%s): %s", key, exc)
            self._available = False
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Cache degeri cozulemedi, siliniyor: %s", key)
            await self.delete(key)
            return None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Degeri JSON olarak TTL ile yazar. TTL'siz yazim yapilmaz."""
        if not self.available:
            return False
        expire = ttl if ttl and ttl > 0 else settings.cache_default_ttl
        try:
            await self._client.setex(  # type: ignore[union-attr]
                key, expire, json.dumps(value, ensure_ascii=False, default=str)
            )
            return True
        except (RedisError, TypeError) as exc:
            logger.warning("Cache yazma hatasi (%s): %s", key, exc)
            return False

    async def delete(self, *keys: str) -> int:
        """Verilen anahtarlari siler, silinen sayisini dondurur."""
        if not self.available or not keys:
            return 0
        try:
            return int(await self._client.delete(*keys))  # type: ignore[union-attr]
        except RedisError as exc:
            logger.warning("Cache silme hatasi: %s", exc)
            return 0

    async def delete_pattern(self, pattern: str) -> int:
        """SCAN ile desene uyan anahtarlari toplu siler (KEYS kullanilmaz)."""
        if not self.available:
            return 0
        removed = 0
        try:
            batch: list[str] = []
            async for key in self._client.scan_iter(match=pattern, count=500):  # type: ignore[union-attr]
                batch.append(key)
                if len(batch) >= 500:
                    removed += int(await self._client.delete(*batch))  # type: ignore[union-attr]
                    batch.clear()
            if batch:
                removed += int(await self._client.delete(*batch))  # type: ignore[union-attr]
        except RedisError as exc:
            logger.warning("Cache desen silme hatasi (%s): %s", pattern, exc)
        return removed

    async def ttl(self, key: str) -> int:
        """Anahtarin kalan TTL degerini saniye olarak dondurur (-1/-2 yoksa)."""
        if not self.available:
            return -2
        try:
            return int(await self._client.ttl(key))  # type: ignore[union-attr]
        except RedisError:
            return -2

    async def incr_window(self, key: str, window_seconds: int) -> int:
        """Sliding window sayaci: ilk artista TTL kurar, sayaci dondurur."""
        if not self.available:
            return 0
        try:
            pipe = self._client.pipeline()  # type: ignore[union-attr]
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            result = await pipe.execute()
            return int(result[0])
        except RedisError as exc:
            logger.warning("Rate limit sayaci hatasi (%s): %s", key, exc)
            return 0

    async def healthy(self) -> bool:
        """Cache saglik kontrolu."""
        if self._client is None:
            return False
        try:
            await self._client.ping()
            self._available = True
            return True
        except RedisError:
            self._available = False
            return False


cache = CacheService()


async def invalidate_public_cache(*extra_keys: str) -> None:
    """Yazma sonrasi public sayfa/API cache'ini temizler (BackgroundTasks icinden cagrilir)."""
    await cache.delete_pattern("http:*")
    await cache.delete_pattern("post:*")
    await cache.delete_pattern("page:*")
    await cache.delete_pattern("tag:*")
    if extra_keys:
        await cache.delete(*extra_keys)
    logger.info("Public cache temizlendi")
