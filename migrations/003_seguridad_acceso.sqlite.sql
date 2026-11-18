-- 003 · Seguridad de acceso: intentos fallidos de login y tokens de recuperación.
-- Las marcas de tiempo se guardan en la hora del negocio (TZ), calculadas por la aplicación.
CREATE TABLE IF NOT EXISTS intentos_login (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correo TEXT NOT NULL,
    ip TEXT NOT NULL,
    momento TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intentos_login ON intentos_login (correo, ip, momento);

CREATE TABLE IF NOT EXISTS tokens_recuperacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expira_en TEXT NOT NULL,
    usado INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
