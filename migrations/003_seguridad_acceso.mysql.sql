-- 003 · Seguridad de acceso: intentos fallidos de login y tokens de recuperación.
-- Las marcas de tiempo se guardan en la hora del negocio (TZ), calculadas por la aplicación.
CREATE TABLE IF NOT EXISTS intentos_login (
    id INT AUTO_INCREMENT PRIMARY KEY,
    correo VARCHAR(100) NOT NULL,
    ip VARCHAR(45) NOT NULL,
    momento DATETIME NOT NULL,
    INDEX idx_intentos_login (correo, ip, momento)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tokens_recuperacion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expira_en DATETIME NOT NULL,
    usado TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_token_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB;
