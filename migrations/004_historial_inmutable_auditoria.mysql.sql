-- 004 · Historia clínica inmutable + auditoría.
-- Editar = nueva nota que referencia a la anterior (corrige_a). Eliminar = anular con motivo.
ALTER TABLE historial_citas
    ADD COLUMN corrige_a INT NULL,
    ADD COLUMN anulada TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN motivo_anulacion VARCHAR(255) NULL,
    ADD CONSTRAINT fk_hist_corrige FOREIGN KEY (corrige_a) REFERENCES historial_citas(id) ON DELETE SET NULL;

-- usuario_id sin llave foránea a propósito: el registro debe conservar el id aunque el usuario se elimine.
CREATE TABLE IF NOT EXISTS auditoria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NULL,
    accion VARCHAR(50) NOT NULL,
    entidad VARCHAR(50) NOT NULL,
    entidad_id INT NULL,
    detalle TEXT NULL,
    override TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    INDEX idx_auditoria_entidad (entidad, entidad_id),
    INDEX idx_auditoria_usuario (usuario_id, created_at)
) ENGINE=InnoDB;
