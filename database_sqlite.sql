-- ====================================================================
-- SISTEMA DE GESTION DE CITAS MEDICAS - UCC  (version SQLite)
-- Esquema CONSOLIDADO: equivale a aplicar migrations/001..006 (*.sqlite.sql).
-- La fuente de verdad son las migraciones: `python init_db.py` las aplica en orden.
-- Use este archivo solo para crear la base a mano; marca las versiones como aplicadas.
-- Sin datos: los datos de demostración están en seed_demo.sql.
-- (tests/test_correcciones.py verifica que este archivo coincide con las migraciones)
-- ====================================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_acceso TEXT
);

-- Horario semanal con vigencia (NULL = indefinido). No se permiten turnos que crucen medianoche.
CREATE TABLE IF NOT EXISTS horarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_inicio TEXT NOT NULL,
    hora_fin TEXT NOT NULL CHECK (hora_fin > hora_inicio),
    vigente_desde TEXT,
    vigente_hasta TEXT
);
CREATE INDEX IF NOT EXISTS idx_horarios_prof_dia ON horarios (profesional_id, dia_semana);

CREATE TABLE IF NOT EXISTS citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha TEXT NOT NULL,
    hora TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'Pendiente' CHECK (estado IN ('Pendiente','Atendida','Cancelada','Inasistida')),
    motivo TEXT NOT NULL DEFAULT 'Consulta general',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    requiere_reprogramacion INTEGER NOT NULL DEFAULT 0 CHECK (requiere_reprogramacion IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_citas_prof_fecha ON citas (profesional_id, fecha);
CREATE INDEX IF NOT EXISTS idx_citas_paciente ON citas (paciente_id);
-- Sin doble reserva: una sola cita activa por profesional/paciente + fecha + hora
CREATE UNIQUE INDEX IF NOT EXISTS uq_citas_prof_activa ON citas (profesional_id, fecha, hora) WHERE estado <> 'Cancelada';
CREATE UNIQUE INDEX IF NOT EXISTS uq_citas_pac_activa ON citas (paciente_id, fecha, hora) WHERE estado <> 'Cancelada';

-- Historia clínica inmutable: corregir = nueva nota (corrige_a); eliminar = anular con motivo
CREATE TABLE IF NOT EXISTS historial_citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER NOT NULL REFERENCES citas(id) ON DELETE CASCADE,
    observacion TEXT NOT NULL,
    registrado_por INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE RESTRICT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    corrige_a INTEGER REFERENCES historial_citas(id) ON DELETE SET NULL,
    anulada INTEGER NOT NULL DEFAULT 0,
    motivo_anulacion TEXT
);
CREATE INDEX IF NOT EXISTS idx_historial_corrige ON historial_citas (corrige_a);

-- Cola y registro de correos (modo: pendiente | smtp | demo | error)
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

-- Excepciones por fecha: bloqueo (sin horas = día completo) o turno extra
CREATE TABLE IF NOT EXISTS excepciones_horario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('bloqueo', 'extra')),
    hora_inicio TEXT,
    hora_fin TEXT,
    motivo TEXT NOT NULL,
    creado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK ((hora_inicio IS NULL AND hora_fin IS NULL AND tipo = 'bloqueo')
           OR (hora_inicio IS NOT NULL AND hora_fin IS NOT NULL AND hora_fin > hora_inicio))
);
CREATE INDEX IF NOT EXISTS idx_excepciones_prof_fecha ON excepciones_horario (profesional_id, fecha);

-- Notificaciones internas (006)
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

INSERT OR IGNORE INTO schema_migrations (version, nombre) VALUES
    (1, 'esquema_inicial'), (2, 'citas_sin_doble_reserva'), (3, 'seguridad_acceso'),
    (4, 'historial_inmutable_auditoria'), (5, 'agenda_vigencia_excepciones'),
    (6, 'notificaciones_cuenta');
