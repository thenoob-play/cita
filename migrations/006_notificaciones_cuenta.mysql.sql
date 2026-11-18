-- 006 · Centro de notificaciones dentro de la aplicación + último acceso de la cuenta.
-- Las notificaciones son avisos internos (no correos): cita creada, reprogramada, cancelada, atendida...
CREATE TABLE IF NOT EXISTS notificaciones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'info',
    titulo VARCHAR(120) NOT NULL,
    mensaje VARCHAR(255) NOT NULL,
    url VARCHAR(255) NULL,
    leida TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    INDEX idx_notif_usuario (usuario_id, leida, id),
    CONSTRAINT fk_notif_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB;

ALTER TABLE usuarios ADD COLUMN ultimo_acceso DATETIME NULL;
