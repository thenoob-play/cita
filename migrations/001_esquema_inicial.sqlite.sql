-- 001 · Esquema inicial (equivale al database_sqlite.sql original, sin datos).
-- Usa IF NOT EXISTS para adoptar bases creadas antes de existir las migraciones.
CREATE TABLE IF NOT EXISTS especialidades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    documento TEXT NOT NULL UNIQUE,
    telefono TEXT,
    correo TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('administrador','recepcionista','profesional','paciente')),
    especialidad_id INTEGER REFERENCES especialidades(id) ON DELETE SET NULL ON UPDATE CASCADE,
    activo INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS horarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_inicio TEXT NOT NULL,
    hora_fin TEXT NOT NULL CHECK (hora_fin > hora_inicio),
    UNIQUE (profesional_id, dia_semana, hora_inicio)
);

CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'Pendiente' CHECK (estado IN ('Pendiente','Atendida','Cancelada','Inasistida')),
    motivo TEXT NOT NULL DEFAULT 'Consulta general',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_citas_prof_fecha ON citas (profesional_id, fecha);
CREATE INDEX IF NOT EXISTS idx_citas_paciente ON citas (paciente_id);

CREATE TABLE IF NOT EXISTS historial_citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER NOT NULL REFERENCES citas(id) ON DELETE CASCADE,
    observacion TEXT NOT NULL,
    registrado_por INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recordatorios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER NOT NULL REFERENCES citas(id) ON DELETE CASCADE,
    correo_destino TEXT NOT NULL,
    asunto TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'recordatorio',
    modo TEXT NOT NULL DEFAULT 'demo',
    enviado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
