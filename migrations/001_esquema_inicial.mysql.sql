-- 001 · Esquema inicial (equivale al database.sql original, sin datos).
-- Usa IF NOT EXISTS para adoptar bases creadas antes de existir las migraciones.
CREATE TABLE IF NOT EXISTS especialidades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    documento VARCHAR(30) NOT NULL UNIQUE,
    telefono VARCHAR(30) DEFAULT NULL,
    correo VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    rol ENUM('administrador','recepcionista','profesional','paciente') NOT NULL,
    especialidad_id INT DEFAULT NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_usuarios_rol (rol),
    CONSTRAINT fk_usuario_especialidad FOREIGN KEY (especialidad_id)
        REFERENCES especialidades(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS horarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    profesional_id INT NOT NULL,
    dia_semana TINYINT NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    UNIQUE KEY uq_horario (profesional_id, dia_semana, hora_inicio),
    CONSTRAINT chk_dia CHECK (dia_semana BETWEEN 0 AND 6),
    CONSTRAINT chk_horas CHECK (hora_fin > hora_inicio),
    CONSTRAINT fk_horario_prof FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS citas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    paciente_id INT NOT NULL,
    profesional_id INT NOT NULL,
    fecha DATE NOT NULL,
    hora TIME NOT NULL,
    estado ENUM('Pendiente','Atendida','Cancelada','Inasistida') NOT NULL DEFAULT 'Pendiente',
    motivo VARCHAR(255) NOT NULL DEFAULT 'Consulta general',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_citas_prof_fecha (profesional_id, fecha),
    INDEX idx_citas_paciente (paciente_id),
    CONSTRAINT fk_cita_paciente FOREIGN KEY (paciente_id) REFERENCES usuarios(id) ON DELETE RESTRICT,
    CONSTRAINT fk_cita_prof FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS historial_citas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cita_id INT NOT NULL,
    observacion TEXT NOT NULL,
    registrado_por INT NOT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_hist_cita FOREIGN KEY (cita_id) REFERENCES citas(id) ON DELETE CASCADE,
    CONSTRAINT fk_hist_user FOREIGN KEY (registrado_por) REFERENCES usuarios(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recordatorios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cita_id INT NOT NULL,
    correo_destino VARCHAR(100) NOT NULL,
    asunto VARCHAR(150) NOT NULL,
    mensaje TEXT NOT NULL,
    tipo VARCHAR(20) NOT NULL DEFAULT 'recordatorio',
    modo VARCHAR(10) NOT NULL DEFAULT 'demo',
    enviado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rec_cita FOREIGN KEY (cita_id) REFERENCES citas(id) ON DELETE CASCADE
) ENGINE=InnoDB;
