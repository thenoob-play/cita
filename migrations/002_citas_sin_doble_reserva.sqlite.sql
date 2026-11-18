-- 002 · Sin doble reserva: una sola cita activa (estado <> 'Cancelada') por
--       profesional+fecha+hora y por paciente+fecha+hora. Índices únicos parciales.
-- Si la base tiene duplicados previos, esta migración falla: resuélvalos (cancele uno) y reintente.
CREATE UNIQUE INDEX IF NOT EXISTS uq_citas_prof_activa ON citas (profesional_id, fecha, hora)
    WHERE estado <> 'Cancelada';
CREATE UNIQUE INDEX IF NOT EXISTS uq_citas_pac_activa ON citas (paciente_id, fecha, hora)
    WHERE estado <> 'Cancelada';
