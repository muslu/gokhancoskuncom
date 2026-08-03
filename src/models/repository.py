"""Veri erisim katmani.

Tum sorgular `PostgresService` uzerinden, parameterized (`:isim` + dict) olarak
calisir. `SELECT *` kullanilmaz; her sorguda ihtiyac duyulan kolonlar listelenir.
"""

from datetime import UTC, datetime
from typing import Any

from src.colorlogger import logger
from src.config import settings
from src.crypto import encrypt_password, hash_api_token, verify_password
from src.db import db
from src.models.schemas import (
    PostCreate,
    PostStatus,
    PostUpdate,
    ProfileUpdate,
)
from src.services.markdown_service import (
    make_slug,
    make_summary,
    reading_minutes,
    render_markdown,
)

# Tekrar eden kolon listeleri — SELECT * yerine acik kolonlar
_POST_LIST_COLS = """
    p.id, p.slug, p.title, p.summary, p.cover_image, p.status,
    p.is_featured, p.reading_minutes, p.view_count,
    p.published_at, p.updated_at
"""

_POST_DETAIL_COLS = f"""
    {_POST_LIST_COLS},
    p.content_md, p.content_html, p.meta_description, p.created_at,
    u.full_name AS author_name
"""

_PAGE_COLS = """
    slug, title, content_md, content_html, meta_description,
    is_published, show_in_menu, sort_order, updated_at
"""

_PROFILE_COLS = """
    full_name, title, tagline, bio_md, bio_html, avatar_url,
    email, phone, location, socials, updated_at
"""


# ==================================================================
# Kullanicilar
# ==================================================================
async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Kullanici adina gore aktif kullaniciyi dondurur."""
    return await db.fetch_one(
        """
        SELECT id, username, email, full_name, password_enc, role,
               is_active, last_login_at
        FROM users
        WHERE username = :username AND is_active
        """,
        {"username": username},
    )


async def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Id'ye gore aktif kullaniciyi dondurur."""
    return await db.fetch_one(
        """
        SELECT id, username, email, full_name, role, is_active, last_login_at
        FROM users
        WHERE id = :user_id AND is_active
        """,
        {"user_id": user_id},
    )


async def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Kullanici adi + parola dogrular; basarisizsa None dondurur."""
    user = await get_user_by_username(username)
    if user is None:
        return None
    if not verify_password(password, user["password_enc"]):
        return None
    await db.execute_write(
        "UPDATE users SET last_login_at = now() WHERE id = :user_id",
        {"user_id": user["id"]},
    )
    user.pop("password_enc", None)
    return user


async def change_password(user_id: int, new_password: str) -> None:
    """Kullanicinin parolasini Fernet ile sifreleyip gunceller."""
    await db.execute_write(
        """
        UPDATE users
        SET password_enc = :password_enc, updated_at = now()
        WHERE id = :user_id
        """,
        {"password_enc": encrypt_password(new_password), "user_id": user_id},
    )


async def ensure_admin_user() -> int | None:
    """Ilk yonetici hesabini olusturur (varsa dokunmaz), kullanici id'sini dondurur."""
    existing = await db.fetch_one(
        "SELECT id FROM users WHERE username = :username",
        {"username": settings.admin_username},
    )
    if existing:
        return int(existing["id"])
    if not settings.admin_password:
        logger.warning("ADMIN_PASSWORD tanimli degil — yonetici hesabi olusturulmadi")
        return None
    rows = await db.execute_write(
        """
        INSERT INTO users (username, email, full_name, password_enc, role)
        VALUES (:username, :email, :full_name, :password_enc, 'admin')
        ON CONFLICT (username) DO NOTHING
        RETURNING id
        """,
        {
            "username": settings.admin_username,
            "email": settings.admin_email,
            "full_name": "Gökhan Coşkun",
            "password_enc": encrypt_password(settings.admin_password),
        },
    )
    if rows:
        logger.info("Yonetici hesabi olusturuldu: %s", settings.admin_username)
        return int(rows[0]["id"])
    return None


# ==================================================================
# Etiketler
# ==================================================================
async def _sync_post_tags(post_id: int, tags: list[str]) -> None:
    """Yazinin etiketlerini verilen listeyle esitler."""
    await db.execute_write(
        "DELETE FROM post_tags WHERE post_id = :post_id", {"post_id": post_id}
    )
    for name in tags:
        slug = make_slug(name, max_length=80)
        rows = await db.execute_write(
            """
            INSERT INTO tags (slug, name) VALUES (:slug, :name)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            {"slug": slug, "name": name},
        )
        if not rows:
            continue
        await db.execute_write(
            """
            INSERT INTO post_tags (post_id, tag_id) VALUES (:post_id, :tag_id)
            ON CONFLICT DO NOTHING
            """,
            {"post_id": post_id, "tag_id": rows[0]["id"]},
        )


async def _attach_tags(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Yazi listesine etiketleri tek sorguda ekler (N+1 onlenir)."""
    if not posts:
        return posts
    ids = [int(p["id"]) for p in posts]
    rows = await db.execute_query(
        """
        SELECT pt.post_id, t.name
        FROM post_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE pt.post_id = ANY(:ids)
        ORDER BY t.name
        """,
        {"ids": ids},
    )
    grouped: dict[int, list[str]] = {}
    for row in rows:
        grouped.setdefault(int(row["post_id"]), []).append(row["name"])
    for post in posts:
        post["tags"] = grouped.get(int(post["id"]), [])
    return posts


async def list_tags(limit: int = 50) -> list[dict[str, Any]]:
    """Yayindaki yazi sayisiyla birlikte etiket listesi dondurur."""
    return await db.execute_query(
        """
        SELECT t.slug, t.name, count(p.id) AS post_count
        FROM tags t
        JOIN post_tags pt ON pt.tag_id = t.id
        JOIN posts p ON p.id = pt.post_id AND p.status = 'published'
        GROUP BY t.slug, t.name
        HAVING count(p.id) > 0
        ORDER BY count(p.id) DESC, t.name
        LIMIT :limit
        """,
        {"limit": limit},
    )


# ==================================================================
# Blog yazilari — okuma
# ==================================================================
async def list_posts(
    page: int = 1,
    per_page: int = 10,
    status: PostStatus | None = PostStatus.PUBLISHED,
    tag: str | None = None,
    search: str | None = None,
    featured_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Sayfalanmis yazi listesi + toplam sayi dondurur."""
    where = ["1 = 1"]
    params: dict[str, Any] = {"limit": per_page, "offset": (page - 1) * per_page}

    if status is not None:
        where.append("p.status = :status")
        params["status"] = status.value
    if featured_only:
        where.append("p.is_featured")
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM post_tags pt JOIN tags t ON t.id = pt.tag_id "
            "WHERE pt.post_id = p.id AND t.slug = :tag)"
        )
        params["tag"] = tag
    if search:
        where.append(
            "(p.search_tsv @@ plainto_tsquery('simple', unaccent(:search)) "
            "OR p.title ILIKE :search_like)"
        )
        params["search"] = search
        params["search_like"] = f"%{search}%"

    clause = " AND ".join(where)
    order = (
        "p.published_at DESC NULLS LAST, p.id DESC"
        if status == PostStatus.PUBLISHED
        else "p.updated_at DESC, p.id DESC"
    )

    rows = await db.execute_query(
        f"""
        SELECT {_POST_LIST_COLS}
        FROM posts p
        WHERE {clause}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
        """,
        params,
    )
    total = await db.fetch_value(
        f"SELECT count(*) AS total FROM posts p WHERE {clause}",
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    return await _attach_tags(rows), int(total or 0)


async def get_post_by_slug(
    slug: str, only_published: bool = True
) -> dict[str, Any] | None:
    """Slug'a gore yaziyi etiketleriyle birlikte dondurur."""
    params: dict[str, Any] = {"slug": slug}
    status_clause = "AND p.status = 'published'" if only_published else ""
    row = await db.fetch_one(
        f"""
        SELECT {_POST_DETAIL_COLS}
        FROM posts p
        JOIN users u ON u.id = p.author_id
        WHERE p.slug = :slug {status_clause}
        """,
        params,
    )
    if row is None:
        return None
    (enriched,) = await _attach_tags([row])
    return enriched


async def get_adjacent_posts(published_at: datetime | None, post_id: int) -> dict[str, Any]:
    """Yazi detayinda gosterilecek onceki/sonraki yaziyi dondurur."""
    params = {"published_at": published_at, "post_id": post_id}
    previous = await db.fetch_one(
        """
        SELECT slug, title FROM posts
        WHERE status = 'published'
          AND (published_at, id) < (:published_at, :post_id)
        ORDER BY published_at DESC, id DESC
        LIMIT 1
        """,
        params,
    )
    following = await db.fetch_one(
        """
        SELECT slug, title FROM posts
        WHERE status = 'published'
          AND (published_at, id) > (:published_at, :post_id)
        ORDER BY published_at ASC, id ASC
        LIMIT 1
        """,
        params,
    )
    return {"previous": previous, "next": following}


async def related_posts(post_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """Ortak etiket sayisina gore benzer yazilari dondurur."""
    rows = await db.execute_query(
        f"""
        SELECT {_POST_LIST_COLS}, count(pt2.tag_id) AS ortak
        FROM posts p
        JOIN post_tags pt2 ON pt2.post_id = p.id
        WHERE p.status = 'published'
          AND p.id <> :post_id
          AND pt2.tag_id IN (SELECT tag_id FROM post_tags WHERE post_id = :post_id)
        GROUP BY p.id
        ORDER BY count(pt2.tag_id) DESC, p.published_at DESC
        LIMIT :limit
        """,
        {"post_id": post_id, "limit": limit},
    )
    return await _attach_tags(rows)


async def increment_view_by_slug(slug: str) -> None:
    """Yayindaki yazinin okunma sayacini slug uzerinden artirir.

    Sayac `@okuma_sayaci` dekoratorunden cagrilir; dekorator onbellegin disinda
    calistigi icin elinde yalnizca slug vardir, kayit kimligi yoktur.
    Taslaklar sayilmaz.
    """
    try:
        await db.execute_write(
            """
            UPDATE posts SET view_count = view_count + 1
            WHERE slug = :slug AND status = 'published'
            """,
            {"slug": slug},
        )
    except Exception as exc:  # noqa: BLE001 — sayac hatasi istegi bozmamali
        logger.warning("Okunma sayaci guncellenemedi (%s): %s", slug, exc)


async def increment_view_count(post_id: int) -> None:
    """Goruntulenme sayacini artirir (BackgroundTasks icinden cagrilir)."""
    try:
        await db.execute_write(
            "UPDATE posts SET view_count = view_count + 1 WHERE id = :post_id",
            {"post_id": post_id},
        )
    except Exception as exc:  # noqa: BLE001 — sayac hatasi istegi bozmamali
        logger.warning("Goruntulenme sayaci guncellenemedi (%s): %s", post_id, exc)


async def slug_exists(slug: str, exclude_id: int | None = None) -> bool:
    """Slug'in kullanimda olup olmadigini kontrol eder."""
    result = await db.fetch_value(
        """
        SELECT 1 FROM posts
        WHERE slug = :slug
          AND (CAST(:exclude_id AS BIGINT) IS NULL OR id <> :exclude_id)
        LIMIT 1
        """,
        {"slug": slug, "exclude_id": exclude_id},
    )
    return result is not None


async def _unique_slug(base: str, exclude_id: int | None = None) -> str:
    """Cakisma varsa sonuna sayi ekleyerek benzersiz slug uretir."""
    slug = base
    counter = 2
    while await slug_exists(slug, exclude_id):
        slug = f"{base}-{counter}"
        counter += 1
        if counter > 500:  # patolojik durum korumasi
            raise ValueError("Benzersiz slug üretilemedi")
    return slug


# ==================================================================
# Blog yazilari — yazma
# ==================================================================
async def create_post(payload: PostCreate, author_id: int) -> dict[str, Any]:
    """Yeni blog yazisi olusturur ve detayini dondurur."""
    base_slug = payload.slug or make_slug(payload.title)
    slug = await _unique_slug(base_slug)
    content_html = render_markdown(payload.content_md)
    summary = payload.summary or make_summary(payload.content_md)
    published_at = payload.published_at
    if payload.status == PostStatus.PUBLISHED and published_at is None:
        published_at = datetime.now(UTC)

    rows = await db.execute_write(
        """
        INSERT INTO posts (
            slug, title, summary, content_md, content_html, cover_image,
            meta_description, status, is_featured, reading_minutes,
            author_id, published_at
        ) VALUES (
            :slug, :title, :summary, :content_md, :content_html, :cover_image,
            :meta_description, :status, :is_featured, :reading_minutes,
            :author_id, :published_at
        )
        RETURNING id, slug
        """,
        {
            "slug": slug,
            "title": payload.title,
            "summary": summary,
            "content_md": payload.content_md,
            "content_html": content_html,
            "cover_image": payload.cover_image,
            "meta_description": payload.meta_description or summary[:300],
            "status": payload.status.value,
            "is_featured": payload.is_featured,
            "reading_minutes": reading_minutes(payload.content_md),
            "author_id": author_id,
            "published_at": published_at,
        },
    )
    post_id = int(rows[0]["id"])
    if payload.tags:
        await _sync_post_tags(post_id, payload.tags)
    logger.info("Yazi olusturuldu: %s (id=%s)", slug, post_id)
    result = await get_post_by_slug(slug, only_published=False)
    assert result is not None
    return result


async def update_post(slug: str, payload: PostUpdate) -> dict[str, Any] | None:
    """Gonderilen alanlari gunceller; yazi yoksa None dondurur."""
    current = await db.fetch_one(
        "SELECT id, slug, status, published_at FROM posts WHERE slug = :slug",
        {"slug": slug},
    )
    if current is None:
        return None

    post_id = int(current["id"])
    fields: list[str] = []
    params: dict[str, Any] = {"post_id": post_id}
    data = payload.model_dump(exclude_unset=True)

    if "title" in data and data["title"]:
        fields.append("title = :title")
        params["title"] = data["title"]

    if "content_md" in data and data["content_md"]:
        fields.append("content_md = :content_md")
        fields.append("content_html = :content_html")
        fields.append("reading_minutes = :reading_minutes")
        params["content_md"] = data["content_md"]
        params["content_html"] = render_markdown(data["content_md"])
        params["reading_minutes"] = reading_minutes(data["content_md"])
        if "summary" not in data:
            fields.append("summary = :summary")
            params["summary"] = make_summary(data["content_md"])

    for column in ("summary", "cover_image", "meta_description"):
        if column in data:
            fields.append(f"{column} = :{column}")
            params[column] = data[column]

    if "is_featured" in data:
        fields.append("is_featured = :is_featured")
        params["is_featured"] = data["is_featured"]

    if "status" in data and data["status"] is not None:
        new_status = data["status"].value if hasattr(data["status"], "value") else data["status"]
        fields.append("status = :status")
        params["status"] = new_status
        # Ilk kez yayina alindiysa yayin tarihini simdi olarak isaretle
        if new_status == "published" and current["published_at"] is None:
            fields.append("published_at = COALESCE(:published_at, now())")
            params["published_at"] = data.get("published_at")
        elif "published_at" in data:
            fields.append("published_at = :published_at")
            params["published_at"] = data["published_at"]
    elif "published_at" in data:
        fields.append("published_at = :published_at")
        params["published_at"] = data["published_at"]

    if fields:
        fields.append("updated_at = now()")
        await db.execute_write(
            f"UPDATE posts SET {', '.join(fields)} WHERE id = :post_id", params
        )

    if data.get("tags") is not None:
        await _sync_post_tags(post_id, data["tags"])

    logger.info("Yazi guncellendi: %s (id=%s)", slug, post_id)
    return await get_post_by_slug(current["slug"], only_published=False)


async def set_post_status(slug: str, status: PostStatus) -> dict[str, Any] | None:
    """Yaziyi yayina alir veya taslaga cevirir."""
    return await update_post(slug, PostUpdate(status=status))


async def delete_post(slug: str) -> bool:
    """Yaziyi siler; silinen kayit varsa True dondurur."""
    rows = await db.execute_write(
        "DELETE FROM posts WHERE slug = :slug RETURNING id", {"slug": slug}
    )
    if rows:
        logger.info("Yazi silindi: %s", slug)
    return bool(rows)


async def post_stats() -> dict[str, int]:
    """Panel gostergesi icin ozet sayilar."""
    row = await db.fetch_one(
        """
        SELECT
            count(*) FILTER (WHERE status = 'published') AS yayinda,
            count(*) FILTER (WHERE status = 'draft')     AS taslak,
            COALESCE(sum(view_count), 0)                 AS goruntulenme,
            count(*)                                     AS toplam
        FROM posts
        """
    )
    unread = await db.fetch_value(
        "SELECT count(*) AS n FROM contact_messages WHERE NOT is_read"
    )
    return {
        "yayinda": int(row["yayinda"]) if row else 0,
        "taslak": int(row["taslak"]) if row else 0,
        "goruntulenme": int(row["goruntulenme"]) if row else 0,
        "toplam": int(row["toplam"]) if row else 0,
        "okunmamis_mesaj": int(unread or 0),
    }


# ==================================================================
# Sayfalar
# ==================================================================
async def get_page(slug: str, only_published: bool = True) -> dict[str, Any] | None:
    """Slug'a gore statik sayfayi dondurur."""
    clause = "AND is_published" if only_published else ""
    return await db.fetch_one(
        f"SELECT {_PAGE_COLS} FROM pages WHERE slug = :slug {clause}",
        {"slug": slug},
    )


async def list_pages(menu_only: bool = False) -> list[dict[str, Any]]:
    """Sayfalari sira numarasina gore listeler."""
    clause = "WHERE is_published AND show_in_menu" if menu_only else ""
    return await db.execute_query(
        f"SELECT {_PAGE_COLS} FROM pages {clause} ORDER BY sort_order, title"
    )


async def update_page(slug: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Statik sayfayi gunceller; yoksa None dondurur."""
    fields: list[str] = []
    params: dict[str, Any] = {"slug": slug}

    if data.get("title"):
        fields.append("title = :title")
        params["title"] = data["title"]
    if data.get("content_md") is not None:
        fields.append("content_md = :content_md")
        fields.append("content_html = :content_html")
        params["content_md"] = data["content_md"]
        params["content_html"] = render_markdown(data["content_md"])
    for column in ("meta_description", "is_published", "show_in_menu", "sort_order"):
        if data.get(column) is not None:
            fields.append(f"{column} = :{column}")
            params[column] = data[column]

    if not fields:
        return await get_page(slug, only_published=False)

    fields.append("updated_at = now()")
    rows = await db.execute_write(
        f"UPDATE pages SET {', '.join(fields)} WHERE slug = :slug RETURNING slug", params
    )
    if not rows:
        return None
    logger.info("Sayfa guncellendi: %s", slug)
    return await get_page(slug, only_published=False)


# ==================================================================
# Profil (kisisel bilgiler)
# ==================================================================
async def get_profile() -> dict[str, Any]:
    """Tekil profil kaydini dondurur (yoksa varsayilanla olusturur)."""
    row = await db.fetch_one(f"SELECT {_PROFILE_COLS} FROM profile WHERE id = 1")
    if row is None:
        await db.execute_write(
            "INSERT INTO profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )
        row = await db.fetch_one(f"SELECT {_PROFILE_COLS} FROM profile WHERE id = 1")
    assert row is not None
    return row


async def update_profile(payload: ProfileUpdate) -> dict[str, Any]:
    """Profil bilgilerini gunceller."""
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    fields: list[str] = []
    params: dict[str, Any] = {}

    for column in ("full_name", "title", "tagline", "avatar_url", "email", "phone", "location"):
        if column in data:
            fields.append(f"{column} = :{column}")
            params[column] = str(data[column])

    if "bio_md" in data:
        fields.append("bio_md = :bio_md")
        fields.append("bio_html = :bio_html")
        params["bio_md"] = data["bio_md"]
        params["bio_html"] = render_markdown(data["bio_md"])

    if "socials" in data:
        import json

        fields.append("socials = CAST(:socials AS jsonb)")
        params["socials"] = json.dumps(data["socials"], ensure_ascii=False)

    if fields:
        fields.append("updated_at = now()")
        await db.execute_write(
            f"UPDATE profile SET {', '.join(fields)} WHERE id = 1", params
        )
        logger.info("Profil guncellendi")
    return await get_profile()


# ==================================================================
# Iletisim mesajlari
# ==================================================================
async def create_contact_message(
    name: str, email: str, subject: str | None, message: str, ip: str
) -> int:
    """Iletisim formu mesajini kaydeder ve id dondurur."""
    rows = await db.execute_write(
        """
        INSERT INTO contact_messages (name, email, subject, message, ip_address)
        VALUES (:name, :email, :subject, :message, CAST(:ip AS inet))
        RETURNING id
        """,
        {"name": name, "email": email, "subject": subject, "message": message, "ip": ip},
    )
    return int(rows[0]["id"]) if rows else 0


async def list_contact_messages(limit: int = 50) -> list[dict[str, Any]]:
    """Son iletisim mesajlarini listeler."""
    return await db.execute_query(
        """
        SELECT id, name, email, subject, message, is_read, created_at,
               replied_at, reply_body
        FROM contact_messages
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


async def get_contact_message(message_id: int) -> dict[str, Any] | None:
    """Tek bir iletisim mesajini dondurur (yanitlamadan once okunur)."""
    return await db.fetch_one(
        """
        SELECT id, name, email, subject, message, is_read, created_at,
               replied_at, reply_body
        FROM contact_messages
        WHERE id = :id
        """,
        {"id": message_id},
    )


async def save_contact_reply(message_id: int, reply_body: str, replied_by: int) -> None:
    """Gonderilen yaniti kaydeder ve mesaji okundu isaretler.

    Yalnizca e-posta **gonderimi basarili olduktan sonra** cagrilir; aksi halde
    panelde yanitlanmis gorunen ama karsi tarafa ulasmamis mesajlar olusur.
    """
    await db.execute_write(
        """
        UPDATE contact_messages
        SET reply_body = :body,
            replied_at = now(),
            replied_by = :user_id,
            is_read    = TRUE
        WHERE id = :id
        """,
        {"id": message_id, "body": reply_body, "user_id": replied_by},
    )


async def mark_message_read(message_id: int) -> None:
    """Mesaji okundu olarak isaretler."""
    await db.execute_write(
        "UPDATE contact_messages SET is_read = TRUE WHERE id = :id", {"id": message_id}
    )


# ==================================================================
# API tokenlari
# ==================================================================
async def create_api_token(
    name: str, scopes: list[str], owner_id: int, expires_days: int | None, raw_token: str
) -> dict[str, Any]:
    """Yeni API token kaydi olusturur (ham token cagirana aittir)."""
    rows = await db.execute_write(
        """
        INSERT INTO api_tokens (name, token_hash, token_prefix, scopes, owner_id, expires_at)
        VALUES (
            :name, :token_hash, :token_prefix, :scopes, :owner_id,
            CASE WHEN CAST(:expires_days AS INT) IS NULL THEN NULL
                 ELSE now() + make_interval(days => CAST(:expires_days AS INT)) END
        )
        RETURNING id, name, token_prefix, scopes, is_active,
                  last_used_at, expires_at, created_at
        """,
        {
            "name": name,
            "token_hash": hash_api_token(raw_token),
            "token_prefix": raw_token[:12],
            "scopes": ",".join(scopes),
            "owner_id": owner_id,
            "expires_days": expires_days,
        },
    )
    logger.info("API token uretildi: %s", name)
    return rows[0]


async def resolve_api_token(raw_token: str) -> dict[str, Any] | None:
    """Ham token'i dogrular ve sahibiyle birlikte token kaydini dondurur."""
    row = await db.fetch_one(
        """
        SELECT t.id, t.name, t.scopes, t.owner_id, u.username, u.role
        FROM api_tokens t
        JOIN users u ON u.id = t.owner_id
        WHERE t.token_hash = :token_hash
          AND t.is_active
          AND u.is_active
          AND (t.expires_at IS NULL OR t.expires_at > now())
        """,
        {"token_hash": hash_api_token(raw_token)},
    )
    if row is not None:
        await db.execute_write(
            "UPDATE api_tokens SET last_used_at = now() WHERE id = :id", {"id": row["id"]}
        )
    return row


async def list_api_tokens(owner_id: int | None = None) -> list[dict[str, Any]]:
    """Token listesini dondurur (ham token asla donmez)."""
    clause = "WHERE owner_id = :owner_id" if owner_id else ""
    return await db.execute_query(
        f"""
        SELECT id, name, token_prefix, scopes, is_active,
               last_used_at, expires_at, created_at
        FROM api_tokens {clause}
        ORDER BY created_at DESC
        """,
        {"owner_id": owner_id} if owner_id else {},
    )


async def revoke_api_token(token_id: int) -> bool:
    """Token'i pasifize eder."""
    rows = await db.execute_write(
        "UPDATE api_tokens SET is_active = FALSE WHERE id = :id RETURNING id",
        {"id": token_id},
    )
    return bool(rows)


# ==================================================================
# Denetim kaydi
# ==================================================================
async def write_audit(
    actor: str,
    action: str,
    entity: str,
    entity_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
    actor_type: str = "user",
) -> None:
    """Denetim kaydi yazar (BackgroundTasks icinden cagrilir)."""
    import json

    try:
        await db.execute_write(
            """
            INSERT INTO audit_log (actor, actor_type, action, entity, entity_id, detail, ip_address)
            VALUES (
                :actor, :actor_type, :action, :entity, :entity_id,
                CAST(:detail AS jsonb),
                CASE WHEN :ip IS NULL THEN NULL ELSE CAST(:ip AS inet) END
            )
            """,
            {
                "actor": actor,
                "actor_type": actor_type,
                "action": action,
                "entity": entity,
                "entity_id": str(entity_id) if entity_id is not None else None,
                "detail": json.dumps(detail or {}, ensure_ascii=False, default=str),
                "ip": ip,
            },
        )
    except Exception as exc:  # noqa: BLE001 — audit hatasi istegi bozmamali
        logger.error("Audit kaydi yazilamadi: %s", exc)


async def list_audit(limit: int = 100) -> list[dict[str, Any]]:
    """Son denetim kayitlarini listeler."""
    return await db.execute_query(
        """
        SELECT actor, actor_type, action, entity, entity_id, detail, ip_address, created_at
        FROM audit_log
        ORDER BY created_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
