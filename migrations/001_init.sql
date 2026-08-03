-- ------------------------------------------------------------------
-- 001_init.sql — gokhancoskun.com baslangic semasi
-- Idempotent: tekrar calistirilabilir.
-- ------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ---------------------------------------------------------------
-- Kullanicilar (panel girisi)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    full_name     VARCHAR(150),
    password_enc  TEXT         NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'editor',
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT users_role_chk CHECK (role IN ('admin', 'editor'))
);

CREATE INDEX IF NOT EXISTS idx_users_active
    ON users (username) WHERE is_active;

-- ---------------------------------------------------------------
-- Etiketler
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tags (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug       VARCHAR(80) NOT NULL UNIQUE,
    name       VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- Blog yazilari
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug             VARCHAR(220) NOT NULL UNIQUE,
    title            VARCHAR(220) NOT NULL,
    summary          VARCHAR(500),
    content_md       TEXT         NOT NULL,
    content_html     TEXT         NOT NULL,
    cover_image      VARCHAR(500),
    meta_description VARCHAR(300),
    status           VARCHAR(20)  NOT NULL DEFAULT 'draft',
    is_featured      BOOLEAN      NOT NULL DEFAULT FALSE,
    reading_minutes  SMALLINT     NOT NULL DEFAULT 1,
    view_count       BIGINT       NOT NULL DEFAULT 0,
    author_id        BIGINT       NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    published_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT posts_status_chk CHECK (status IN ('draft', 'published'))
);

-- Yayindaki yazilarin tarih sirali listesi (blog listesi ana sorgusu)
CREATE INDEX IF NOT EXISTS idx_posts_published
    ON posts (published_at DESC) WHERE status = 'published';

-- One cikan yazilar (anasayfa)
CREATE INDEX IF NOT EXISTS idx_posts_featured
    ON posts (published_at DESC) WHERE status = 'published' AND is_featured;

-- Yabanci anahtar indexi
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts (author_id);

-- Panel listesi (durum + guncelleme sirasi)
CREATE INDEX IF NOT EXISTS idx_posts_status_updated ON posts (status, updated_at DESC);

-- Baslik uzerinde bulanik arama
CREATE INDEX IF NOT EXISTS idx_posts_title_trgm
    ON posts USING gin (title gin_trgm_ops);

-- Tam metin arama (Turkce konfigurasyonu yoksa 'simple' ile kurulur)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_tsv tsvector;

CREATE INDEX IF NOT EXISTS idx_posts_search ON posts USING gin (search_tsv);

CREATE OR REPLACE FUNCTION posts_search_tsv_update() RETURNS trigger AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', unaccent(coalesce(NEW.title, ''))), 'A') ||
        setweight(to_tsvector('simple', unaccent(coalesce(NEW.summary, ''))), 'B') ||
        setweight(to_tsvector('simple', unaccent(coalesce(NEW.content_md, ''))), 'C');
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_posts_search_tsv ON posts;
CREATE TRIGGER trg_posts_search_tsv
    BEFORE INSERT OR UPDATE OF title, summary, content_md ON posts
    FOR EACH ROW EXECUTE FUNCTION posts_search_tsv_update();

-- ---------------------------------------------------------------
-- Yazi <-> etiket iliskisi
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS post_tags (
    post_id BIGINT NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
    tag_id  BIGINT NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);

-- Etikete gore yazi listesi icin ters yon index
CREATE INDEX IF NOT EXISTS idx_post_tags_tag ON post_tags (tag_id, post_id);

-- ---------------------------------------------------------------
-- Statik sayfalar (hakkimda, iletisim vb.)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pages (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug             VARCHAR(80)  NOT NULL UNIQUE,
    title            VARCHAR(200) NOT NULL,
    content_md       TEXT         NOT NULL DEFAULT '',
    content_html     TEXT         NOT NULL DEFAULT '',
    meta_description VARCHAR(300),
    is_published     BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order       SMALLINT     NOT NULL DEFAULT 0,
    show_in_menu     BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pages_menu
    ON pages (sort_order) WHERE is_published AND show_in_menu;

-- ---------------------------------------------------------------
-- Kisisel profil (tek satir — id = 1)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profile (
    id          SMALLINT     PRIMARY KEY DEFAULT 1,
    full_name   VARCHAR(150) NOT NULL DEFAULT 'Gökhan Coşkun',
    title       VARCHAR(200) NOT NULL DEFAULT '',
    tagline     VARCHAR(300) NOT NULL DEFAULT '',
    bio_md      TEXT         NOT NULL DEFAULT '',
    bio_html    TEXT         NOT NULL DEFAULT '',
    avatar_url  VARCHAR(500),
    email       VARCHAR(255),
    phone       VARCHAR(50),
    location    VARCHAR(150),
    socials     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT profile_single_row CHECK (id = 1)
);

-- ---------------------------------------------------------------
-- Iletisim mesajlari
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contact_messages (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       VARCHAR(150) NOT NULL,
    email      VARCHAR(255) NOT NULL,
    subject    VARCHAR(200),
    message    TEXT         NOT NULL,
    ip_address INET,
    is_read    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contact_unread
    ON contact_messages (created_at DESC) WHERE NOT is_read;

-- ---------------------------------------------------------------
-- API tokenlari (MCP istemcisi buradan yetkilenir)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    token_hash   VARCHAR(64)  NOT NULL UNIQUE,
    token_prefix VARCHAR(16)  NOT NULL,
    scopes       VARCHAR(200) NOT NULL DEFAULT 'posts:read,posts:write',
    owner_id     BIGINT       NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_owner ON api_tokens (owner_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_active
    ON api_tokens (token_hash) WHERE is_active;

-- ---------------------------------------------------------------
-- Denetim kaydi
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor       VARCHAR(100) NOT NULL,
    actor_type  VARCHAR(20)  NOT NULL DEFAULT 'user',
    action      VARCHAR(50)  NOT NULL,
    entity      VARCHAR(50)  NOT NULL,
    entity_id   VARCHAR(220),
    detail      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    ip_address  INET,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log (entity, entity_id);

-- ---------------------------------------------------------------
-- Baslangic verisi
-- ---------------------------------------------------------------
INSERT INTO profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

INSERT INTO pages (slug, title, content_md, content_html, sort_order, show_in_menu)
VALUES
    ('hakkimda', 'Hakkımda', '', '', 1, TRUE),
    ('iletisim', 'İletişim', '', '', 2, TRUE)
ON CONFLICT (slug) DO NOTHING;
