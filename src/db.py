"""PostgreSQL erisim servisi.

Tum sorgular bu sinif uzerinden calisir — router/model katmani dogrudan
engine veya session kullanmaz. Parametreler her zaman `:isim` + dict ile
gecirilir; f-string ile sorgu olusturmak yasaktir.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.colorlogger import logger
from src.config import settings

_WRITE_KEYWORDS = ("insert", "update", "delete", "truncate", "drop", "alter", "create")


class PostgresService:
    """Async PostgreSQL servisi — okuma/yazma ayrimi ve havuz yonetimi."""

    def __init__(self) -> None:
        self._engine = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    def connect(self) -> None:
        """Engine ve sessionmaker'i olusturur (idempotent)."""
        if self._engine is not None:
            return
        connect_args: dict[str, Any] = {}
        if settings.uses_pgbouncer:
            # PgBouncer transaction pooling prepared statement cache ile uyumsuz
            connect_args["statement_cache_size"] = 0
        self._engine = create_async_engine(
            settings.database_url,
            pool_size=settings.postgres_pool_size,
            max_overflow=settings.postgres_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            connect_args=connect_args,
        )
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        logger.info(
            "PostgreSQL havuzu hazir (db=%s, pgbouncer=%s)",
            settings.postgres_db,
            settings.uses_pgbouncer,
        )

    async def disconnect(self) -> None:
        """Baglanti havuzunu kapatir."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
            logger.info("PostgreSQL havuzu kapatildi")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Commit/rollback'i otomatik yoneten async session context manager."""
        if self._sessionmaker is None:
            self.connect()
        assert self._sessionmaker is not None
        async with self._sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except SQLAlchemyError:
                await session.rollback()
                raise

    @staticmethod
    def _assert_read_only(sql: str) -> None:
        """Okuma metoduna yazma sorgusu gelmesini engeller."""
        head = sql.strip().lstrip("(").lower()
        if not (head.startswith("select") or head.startswith("with")):
            raise ValueError("execute_query yalnizca SELECT/WITH sorgulari calistirir")
        for keyword in _WRITE_KEYWORDS:
            if f" {keyword} " in f" {head} ":
                raise ValueError(f"execute_query icinde yazma anahtar kelimesi: {keyword}")

    async def execute_query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """SELECT sorgusu calistirir ve satirlari dict listesi olarak dondurur."""
        self._assert_read_only(sql)
        try:
            async with self.session() as session:
                result = await session.execute(text(sql), params or {})
                return [dict(row) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            logger.error("execute_query hatasi: %s", exc)
            raise

    async def fetch_one(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Tek satir dondurur; sonuc yoksa None."""
        rows = await self.execute_query(sql, params)
        return rows[0] if rows else None

    async def fetch_value(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        """Tek satir/tek kolon deger dondurur (COUNT, EXISTS vb.)."""
        row = await self.fetch_one(sql, params)
        return next(iter(row.values())) if row else None

    async def execute_write(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """INSERT/UPDATE/DELETE calistirir; RETURNING varsa satirlari dondurur."""
        try:
            async with self.session() as session:
                result = await session.execute(text(sql), params or {})
                if result.returns_rows:
                    return [dict(row) for row in result.mappings().all()]
                return []
        except SQLAlchemyError as exc:
            logger.error("execute_write hatasi: %s", exc)
            raise

    async def execute_script(self, sql: str, lock_key: int = 0) -> None:
        """Cok ifadeli migration betigi calistirir (yalnizca acilis/deploy sirasinda).

        asyncpg prepared statement icine birden fazla komut kabul etmez
        ("cannot insert multiple commands into a prepared statement"), bu yuzden
        betik ham surucu baglantisi uzerinden calistirilir.

        `lock_key` verilirse PostgreSQL advisory lock alinir — birden fazla
        gunicorn worker'i ayni migration'i es zamanli calistirmaz.
        """
        if self._engine is None:
            self.connect()
        assert self._engine is not None
        try:
            async with self._engine.begin() as conn:
                raw = await conn.get_raw_connection()
                driver = raw.driver_connection  # asyncpg.Connection
                if lock_key:
                    await driver.execute("SELECT pg_advisory_xact_lock($1)", lock_key)
                await driver.execute(sql)
        except (SQLAlchemyError, OSError) as exc:
            logger.error("execute_script hatasi: %s", exc)
            raise

    async def healthy(self) -> bool:
        """Baglanti saglik kontrolu."""
        try:
            return await self.fetch_value("SELECT 1") == 1
        except SQLAlchemyError:
            return False


db = PostgresService()
