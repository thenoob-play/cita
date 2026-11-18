-- 002 · Sin doble reserva: una sola cita activa (estado <> 'Cancelada') por
--       profesional+fecha+hora y por paciente+fecha+hora.
-- MySQL no tiene índices parciales: columnas generadas que valen NULL cuando la cita
-- está cancelada (UNIQUE admite varios NULL), con índice único sobre ellas.
-- Si la base tiene duplicados previos, esta migración falla: resuélvalos (cancele uno) y reintente.
ALTER TABLE citas
    ADD COLUMN prof_activa INT GENERATED ALWAYS AS (IF(estado <> 'Cancelada', profesional_id, NULL)) STORED,
    ADD COLUMN pac_activa INT GENERATED ALWAYS AS (IF(estado <> 'Cancelada', paciente_id, NULL)) STORED,
    ADD UNIQUE KEY uq_citas_prof_activa (prof_activa, fecha, hora),
    ADD UNIQUE KEY uq_citas_pac_activa (pac_activa, fecha, hora);
