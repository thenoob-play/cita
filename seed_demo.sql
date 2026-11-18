-- ====================================================================
-- DATOS DE DEMOSTRACIÓN (solo desarrollo). NO cargar en producción.
-- Contraseñas (hash PBKDF2-SHA256):
--   admin@citas.com / admin123 · recepcion@citas.com / recep123
--   medico@citas.com, sofia@citas.com / medico123
--   paciente@citas.com, juan@citas.com / paciente123
-- Lo aplica `python init_db.py` cuando APP_ENV=development o con --demo.
-- Sintaxis MySQL; init_db traduce "INSERT IGNORE" a "INSERT OR IGNORE" para SQLite.
-- Idempotente: puede ejecutarse varias veces.
-- ====================================================================
INSERT IGNORE INTO especialidades (nombre) VALUES ('Medicina General'), ('Cardiología'), ('Pediatría'), ('Dermatología'), ('Ginecología'), ('Odontología');
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Carlos Administrador', '100100100', '3001112233', 'admin@citas.com', 'pbkdf2:sha256:1000000$jP76nUwATi3FybrL$4fa7869453cf10d688995437a157e49a41ca3f0820c70105beb86b485bc6469e', 'administrador', NULL);
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Ana Recepcionista', '200200200', '3002223344', 'recepcion@citas.com', 'pbkdf2:sha256:1000000$fgEOkqzeqtjTE4TX$c83ddb8574a06e0c051b6ccecdfed1e8382006c6ed8605752f84b9ecb5f7e24c', 'recepcionista', NULL);
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Dr. Roberto Mendoza', '300300300', '3003334455', 'medico@citas.com', 'pbkdf2:sha256:1000000$HuJCxCXY1XVq9K1u$9a8a3abb39054d4417a922683f06d995ccbd0aee4acd8e92d974b785f4366655', 'profesional', (SELECT id FROM especialidades WHERE nombre='Cardiología'));
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Dra. Sofia Perez', '300300301', '3003334466', 'sofia@citas.com', 'pbkdf2:sha256:1000000$0M9YFIvKuxs5LSZE$0120315656dbe4b764b4dbd5fb21d9780f263e0d18b12c4cc90eb34f32bdd629', 'profesional', (SELECT id FROM especialidades WHERE nombre='Medicina General'));
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Maria Paciente Gomez', '400400400', '3004445566', 'paciente@citas.com', 'pbkdf2:sha256:1000000$vwt6WESYLxtycUG1$dd2df3cdf721f2abea304073ef30752ff3d12eefc0dbf0f61ed90d94cc761b9d', 'paciente', NULL);
INSERT IGNORE INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id) VALUES ('Juan Perez Paciente', '400400401', '3005556677', 'juan@citas.com', 'pbkdf2:sha256:1000000$DhcZPFJbQBvajeaU$ef30dd7961dace7e1bf05753e27673eb9ffc9e30ae68a1b26545ed6a213d12eb', 'paciente', NULL);
-- Horario demo: lunes a viernes 08:00-12:00 y 14:00-17:00, vigencia indefinida
INSERT INTO horarios (profesional_id, dia_semana, hora_inicio, hora_fin)
SELECT u.id, d.dia, '08:00:00', '12:00:00' FROM usuarios u
JOIN (SELECT 0 AS dia UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4) d
WHERE u.rol = 'profesional' AND u.correo IN ('medico@citas.com', 'sofia@citas.com')
  AND NOT EXISTS (SELECT 1 FROM horarios h WHERE h.profesional_id = u.id AND h.dia_semana = d.dia AND h.hora_inicio = '08:00:00');
INSERT INTO horarios (profesional_id, dia_semana, hora_inicio, hora_fin)
SELECT u.id, d.dia, '14:00:00', '17:00:00' FROM usuarios u
JOIN (SELECT 0 AS dia UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4) d
WHERE u.rol = 'profesional' AND u.correo IN ('medico@citas.com', 'sofia@citas.com')
  AND NOT EXISTS (SELECT 1 FROM horarios h WHERE h.profesional_id = u.id AND h.dia_semana = d.dia AND h.hora_inicio = '14:00:00');
