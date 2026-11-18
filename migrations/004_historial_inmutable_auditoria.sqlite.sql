-- 004 · Historia clínica inmutable + auditoría.
-- Editar = nueva nota que referencia a la anterior (corrige_a). Eliminar = anular con motivo.
ALTER TABLE historial_citas ADD COLUMN corrige_a INTEGER REFERENCES historial_citas(id) ON DELETE SET NULL;
ALTER TABLE historial_citas ADD COLUMN anulada INTEGER NOT NULL DEFAULT 0;
ALTER TABLE historial_citas ADD COLUMN motivo_anulacion TEXT;
CREATE INDEX IF NOT EXISTS idx_historial_corrige ON historial_citas (corrige_a);

-- usuario_id sin llave foránea a propósito: el registro debe conservar el id aunque el usuario se elimine.
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER,
    accion TEXT NOT NULL,
    entidad TEXT NOT NULL,
    entidad_id INTEGER,
    detalle TEXT,
    override INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria (entidad, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria (usuario_id, created_at);
