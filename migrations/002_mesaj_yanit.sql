-- ===================================================================
-- 002 — Iletisim mesajlarina panelden yanit verme
--
-- Yanit metni DB'de saklanir: gonderilen e-postanin bir kopyasi burada
-- durmazsa "bu mesaja ne cevap vermistim" sorusunun tek kaynagi Gokhan'in
-- posta kutusu olur. Panel kendi kaydini tutar.
-- ===================================================================

ALTER TABLE contact_messages
    ADD COLUMN IF NOT EXISTS replied_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reply_body  TEXT,
    ADD COLUMN IF NOT EXISTS replied_by  BIGINT REFERENCES users (id) ON DELETE SET NULL;

-- Yanit bekleyen mesajlar listesi panelin en sik baktigi sorgu.
-- Partial index: yanitlanmislar indekste yer kaplamaz.
CREATE INDEX IF NOT EXISTS idx_contact_yanitsiz
    ON contact_messages (created_at DESC) WHERE replied_at IS NULL;

-- Yabanci anahtar kolonuna index (CLAUDE.md kurali)
CREATE INDEX IF NOT EXISTS idx_contact_replied_by
    ON contact_messages (replied_by) WHERE replied_by IS NOT NULL;
