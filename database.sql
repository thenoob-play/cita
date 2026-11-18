-- ====================================================================
-- SISTEMA DE GESTION DE CITAS MEDICAS - UCC
-- Base de datos MySQL 8.0.16+ / MariaDB 10.4+   (se puede importar en phpMyAdmin)
-- Esquema CONSOLIDADO: equivale a aplicar migrations/001..006 (*.mysql.sql).
-- La fuente de verdad son las migraciones: `python init_db.py` las aplica en orden.
-- Sin datos: los datos de demostración (y sus contraseñas) están en seed_demo.sql.
-- ====================================================================
CREATE DATABASE IF NOT EXISTS db_citas_medicas CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE db_citas_medicas;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

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
    ultimo_acceso DATETIME NULL,
    INDEX idx_usuarios_rol (rol),
    CONSTRAINT fk_usuario_especialidad FOREIGN KEY (especialidad_id)
        REFERENCES especialidades(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB;

-- Horario semanal con vigencia (NULL = indefinido). No se permiten turnos que crucen medianoche.
CREATE TABLE IF NOT EXISTS horarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    profesional_id INT NOT NULL,
    dia_semana TINYINT NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    vigente_desde DATE NULL,
    vigente_hasta DATE NULL,
    INDEX idx_horarios_prof_dia (profesional_id, dia_semana),
    CONSTRAINT chk_dia CHECK (dia_semana BETWEEN 0 AND 6),
    CONSTRAINT chk_horas CHECK (hora_fin > hora_inicio),
    CONSTRAINT fk_horario_prof FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Sin doble reserva: columnas generadas = NULL si la cita está cancelada + UNIQUE sobre ellas
CREATE TABLE IF NOT EXISTS citas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    paciente_id INT NOT NULL,
    profesional_id INT NOT NULL,
    fecha DATE NOT NULL,
    hora TIME NOT NULL,
    estado ENUM('Pendiente','Atendida','Cancelada','Inasistida') NOT NULL DEFAULT 'Pendiente',
    motivo VARCHAR(255) NOT NULL DEFAULT 'Consulta general',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    prof_activa INT GENERATED ALWAYS AS (IF(estado <> 'Cancelada', profesional_id, NULL)) STORED,
    pac_activa INT GENERATED ALWAYS AS (IF(estado <> 'Cancelada', paciente_id, NULL)) STORED,
    requiere_reprogramacion TINYINT(1) NOT NULL DEFAULT 0,
    INDEX idx_citas_prof_fecha (profesional_id, fecha),
    INDEX idx_citas_paciente (paciente_id),
    UNIQUE KEY uq_citas_prof_activa (prof_activa, fecha, hora),
    UNIQUE KEY uq_citas_pac_activa (pac_activa, fecha, hora),
    CONSTRAINT fk_cita_paciente FOREIGN KEY (paciente_id) REFERENCES usuarios(id) ON DELETE RESTRICT,
    CONSTRAINT fk_cita_prof FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Historia clínica inmutable: corregir = nueva nota (corrige_a); eliminar = anular con motivo
CREATE TABLE IF NOT EXISTS historial_citas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cita_id INT NOT NULL,
    observacion TEXT NOT NULL,
    registrado_por INT NOT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    corrige_a INT NULL,
    anulada TINYINT(1) NOT NULL DEFAULT 0,
    motivo_anulacion VARCHAR(255) NULL,
    CONSTRAINT fk_hist_cita FOREIGN KEY (cita_id) REFERENCES citas(id) ON DELETE CASCADE,
    CONSTRAINT fk_hist_user FOREIGN KEY (registrado_por) REFERENCES usuarios(id) ON DELETE RESTRICT,
    CONSTRAINT fk_hist_corrige FOREIGN KEY (corrige_a) REFERENCES historial_citas(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Cola y registro de correos (modo: pendiente | smtp | demo | error)
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

-- Excepciones por fecha: bloqueo (sin horas = día completo) o turno extra
CREATE TABLE IF NOT EXISTS excepciones_horario (
    id INT AUTO_INCREMENT PRIMARY KEY,
    profesional_id INT NOT NULL,
    fecha DATE NOT NULL,
    tipo ENUM('bloqueo', 'extra') NOT NULL,
    hora_inicio TIME NULL,
    hora_fin TIME NULL,
    motivo VARCHAR(255) NOT NULL,
    creado_por INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_excepciones_prof_fecha (profesional_id, fecha),
    CONSTRAINT chk_exc_horas CHECK ((hora_inicio IS NULL AND hora_fin IS NULL AND tipo = 'bloqueo')
                                    OR (hora_inicio IS NOT NULL AND hora_fin IS NOT NULL AND hora_fin > hora_inicio)),
    CONSTRAINT fk_exc_prof FOREIGN KEY (profesional_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    CONSTRAINT fk_exc_creador FOREIGN KEY (creado_por) REFERENCES usuarios(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Notificaciones internas (006)
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

INSERT IGNORE INTO schema_migrations (version, nombre) VALUES
    (1, 'esquema_inicial'), (2, 'citas_sin_doble_reserva'), (3, 'seguridad_acceso'),
    (4, 'historial_inmutable_auditoria'), (5, 'agenda_vigencia_excepciones'),
    (6, 'notificaciones_cuenta');
