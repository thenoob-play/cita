-- 005 · Atención solo dentro del horario asignado.
-- * horarios: vigencia (vigente_desde / vigente_hasta, NULL = indefinido). Se elimina el UNIQUE
--   uq_horario porque un bloque cerrado y su reemplazo pueden compartir hora de inicio.
--   Primero se crea otro índice que empiece por profesional_id (lo exige la llave foránea).
-- * citas.requiere_reprogramacion: marca citas que un cambio de horario dejó fuera de bloque.
-- * excepciones_horario: bloqueos (sin horas = día completo) y turnos extra por fecha.
-- No se permiten turnos que crucen medianoche: CHECK hora_fin > hora_inicio (chk_horas, ya existente).
ALTER TABLE horarios ADD INDEX idx_horarios_prof_dia (profesional_id, dia_semana);
ALTER TABLE horarios
    DROP INDEX uq_horario,
    ADD COLUMN vigente_desde DATE NULL,
    ADD COLUMN vigente_hasta DATE NULL;

ALTER TABLE citas ADD COLUMN requiere_reprogramacion TINYINT(1) NOT NULL DEFAULT 0;

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
