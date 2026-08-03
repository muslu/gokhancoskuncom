"""Uygulama yapilandirmasi — tum degerler .env'den okunur, hardcode yasak."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """`.env` dosyasindan okunan uygulama ayarlari."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Uygulama ---
    app_name: str = "Gökhan Coşkun"
    app_env: str = "production"
    debug: bool = False
    site_url: str = "https://gokhancoskun.com"
    panel_url: str = "https://panel.gokhancoskun.com"
    host: str = "127.0.0.1"
    port: int = 8002

    # --- PostgreSQL ---
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "gokhancoskundb"
    postgres_user: str = "gokhancoskun"
    postgres_password: str = ""
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 5
    pgbouncer_host: str = ""
    pgbouncer_port: str = ""

    # --- Valkey / Redis ---
    valkey_host: str = "127.0.0.1"
    valkey_port: int = 6379
    valkey_db: int = 3
    valkey_password: str = ""
    cache_default_ttl: int = 300

    # --- Guvenlik ---
    fernet_key: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    token_expire_minutes: int = 60
    session_cookie_name: str = "gc_session"
    cookie_secure: bool = True

    # --- Rate limit ---
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    login_rate_limit_requests: int = 5
    login_rate_limit_window_seconds: int = 300

    # --- Medya ---
    media_root: str = "media"
    media_url: str = "/media"
    max_upload_mb: int = 8

    # --- Google (Search Console + Analytics) ---
    # Bos birakilirsa ilgili etiket sayfaya HIC basilmaz. "Ileride lazim olur"
    # diye acik birakilan ucuncu-taraf host'u, acik kalan kapidir.
    google_site_verification: str = ""
    ga4_measurement_id: str = ""

    # --- E-posta (iletisim formu bildirimi) ---
    # Sunucuda Postfix zaten calisiyor; varsayilan olarak localhost:25'e teslim
    # edilir, kimlik dogrulama gerekmez. Harici bir SMTP kullanilacaksa
    # smtp_user/smtp_password doldurulur ve smtp_starttls acilir.
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_timeout: int = 15
    mail_from: str = "siteform@gokhancoskun.com"
    mail_from_name: str = "gokhancoskun.com iletişim formu"
    mail_to: str = "gokhancoskun1983@gmail.com"

    # --- Form bot korumasi ---
    # Formun render edildigi an imzali token'a yazilir; gonderim bu araligin
    # disindaysa reddedilir. Alt sinir otomatik doldurmayi, ust sinir eski
    # sayfadan yapilan toplu gonderimi eler.
    form_min_seconds: int = 3
    form_max_seconds: int = 3600

    # --- Ilk yonetici (seed) ---
    admin_username: str = "gokhan"
    admin_email: str = "info@gokhancoskun.com"
    admin_password: str = ""

    @property
    def database_url(self) -> str:
        """PgBouncer tanimliysa onu, degilse dogrudan PostgreSQL'i hedefleyen async DSN."""
        host = self.pgbouncer_host or self.postgres_host
        port = self.pgbouncer_port or self.postgres_port
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{host}:{port}/{self.postgres_db}"
        )

    @property
    def uses_pgbouncer(self) -> bool:
        """PgBouncer arkasinda calisiliyor mu (prepared statement cache kapatilir)."""
        return bool(self.pgbouncer_host)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Surec basina tek Settings ornegi dondurur."""
    return Settings()


settings = get_settings()
