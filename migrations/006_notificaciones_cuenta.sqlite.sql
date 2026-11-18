-- 006 · Centro de notificaciones dentro de la aplicación + último acceso de la cuenta.
-- Las notificaciones son avisos internos (no correos): cita creada, reprogramada, cancelada, atendida...
CREATE TABLE IF NOT EXISTS notificaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'info',
    titulo TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    url TEXT,
    leida INTEGER NOT NULL DEFAULT 0 CHECK (leida IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_usuario ON notificaciones (usuario_id, leida, id);

ALTER TABLE usuarios ADD COLUMN ultimo_acceso TEXT;
