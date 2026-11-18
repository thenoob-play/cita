-- 005 · Atención solo dentro del horario asignado.
-- * horarios: vigencia (vigente_desde / vigente_hasta, NULL = indefinido). Se elimina el UNIQUE
--   (profesional_id, dia_semana, hora_inicio) porque un bloque cerrado y su reemplazo pueden
--   compartir hora de inicio. SQLite no puede quitar restricciones: se reconstruye la tabla.
-- * citas.requiere_reprogramacion: marca citas que un cambio de horario dejó fuera de bloque.
-- * excepciones_horario: bloqueos (sin horas = día completo) y turnos extra por fecha.
-- No se permiten turnos que crucen medianoche: CHECK hora_fin > hora_inicio.
CREATE TABLE horarios_nueva (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profesional_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_inicio TEXT NOT NULL,
    hora_fin TEXT NOT NULL CHECK (hora_fin > hora_inicio),
    vigente_desde TEXT,
    vigente_hasta TEXT
);
INSERT INTO horarios_nueva (id, profesional_id, dia_semana, hora_inicio, hora_fin)
    SELECT id, profesional_id, dia_semana, hora_inicio, hora_fin FROM horarios;
DROP TABLE horarios;
ALTER TABLE horarios_nueva RENAME TO horarios;
CREATE INDEX IF NOT EXISTS idx_horarios_prof_dia ON horarios (profesional_id, dia_semana);

ALTER TABLE citas ADD COLUMN requiere_reprogramacion INTEGER NOT NULL DEFAULT 0
    CHECK (requiere_reprogramacion IN (0, 1));

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
