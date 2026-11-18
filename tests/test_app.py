"""Pruebas de integración (unittest). Ejecutar:  python -m unittest discover -s tests -v
Usan una base SQLite temporal, no tocan su base MySQL."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
import init_db  # noqa: E402
from app import create_app  # noqa: E402


class TestConfig(Config):
    TESTING = True
    DB_ENGINE = "sqlite"
    MAIL_SERVER = ""


def dia_habil(n=1, hora="09:00"):
    d = date.today()
    while n > 0 or d.weekday() > 4:
        d += timedelta(days=1)
        if d.weekday() <= 4:
            n -= 1
    return d.isoformat(), hora


class Base(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        TestConfig.SQLITE_PATH = self.path
        Config.DB_ENGINE, Config.SQLITE_PATH = "sqlite", self.path
        with contextlib.redirect_stdout(io.StringIO()):
            init_db.main(reset=True, demo=True)   # A11: la demo ya no se siembra implícitamente
        self.app = create_app(TestConfig)
        self.c = self.app.test_client()

    def tearDown(self):
        os.path.exists(self.path) and os.remove(self.path)

    # ---- helpers ----
    def tok(self, c=None):
        c = c or self.c
        with c.session_transaction() as s:
            return s.get("_csrf")

    def login(self, correo, pw, c=None):
        c = c or self.c
        c.get("/login")
        return c.post("/login", data={"correo": correo, "password": pw, "_csrf": self.tok(c)}, follow_redirects=True)

    def post(self, url, data=None, c=None, follow=True):
        c = c or self.c
        d = dict(data or {})
        d["_csrf"] = self.tok(c)
        return c.post(url, data=d, follow_redirects=follow)

    def q(self, sql, p=()):
        import sqlite3
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        r = [dict(x) for x in con.execute(sql, p).fetchall()]
        con.close()
        return r

    def uid(self, correo):
        return self.q("SELECT id FROM usuarios WHERE correo=?", (correo,))[0]["id"]

    def html(self, r):
        return r.get_data(as_text=True)

    @contextlib.contextmanager
    def reloj(self, fecha_iso, hhmm="09:10"):
        """Congela el reloj del negocio (America/Bogota) en fecha_iso hhmm. Añadido para la Fase B (B5)."""
        from datetime import timezone
        from zoneinfo import ZoneInfo
        local = datetime.fromisoformat(f"{fecha_iso} {hhmm}").replace(tzinfo=ZoneInfo("America/Bogota"))
        with mock.patch("app.utils._utcnow", return_value=local.astimezone(timezone.utc)):
            yield


class TestAuth(Base):
    def test_login_roles_y_redireccion(self):
        for correo, pw, texto in [("admin@citas.com", "admin123", "Panel de administración"),
                                  ("recepcion@citas.com", "recep123", "Panel de recepción"),
                                  ("medico@citas.com", "medico123", "Mi agenda"),
                                  ("paciente@citas.com", "paciente123", "Portal del paciente")]:
            c = self.app.test_client()
            r = self.login(correo, pw, c)
            self.assertEqual(r.status_code, 200)
            self.assertIn(texto, self.html(r), correo)

    def test_password_incorrecta_y_hash(self):
        r = self.login("admin@citas.com", "mala")
        self.assertIn("incorrectos", self.html(r))
        h = self.q("SELECT password_hash FROM usuarios WHERE correo='admin@citas.com'")[0]["password_hash"]
        self.assertTrue(h.startswith("pbkdf2:sha256"))
        self.assertNotIn("admin123", h)

    def test_csrf_obligatorio(self):
        self.c.get("/login")
        r = self.c.post("/login", data={"correo": "admin@citas.com", "password": "admin123"})
        self.assertEqual(r.status_code, 400)

    def test_rutas_protegidas_y_roles(self):
        r = self.c.get("/admin/", follow_redirects=True)
        self.assertIn("Iniciar sesión", self.html(r))
        self.login("paciente@citas.com", "paciente123")
        self.assertEqual(self.c.get("/admin/").status_code, 403)
        self.assertEqual(self.c.get("/recepcion/citas").status_code, 403)
        self.assertEqual(self.c.get("/profesional/").status_code, 403)

    def test_logout_post(self):
        self.login("admin@citas.com", "admin123")
        r = self.post("/logout")
        self.assertIn("Sesión cerrada", self.html(r))
        self.assertEqual(self.c.get("/admin/").status_code, 302)

    def test_usuario_desactivado_pierde_acceso(self):
        self.login("paciente@citas.com", "paciente123")
        import sqlite3
        con = sqlite3.connect(self.path)
        con.execute("UPDATE usuarios SET activo=0 WHERE correo='paciente@citas.com'")
        con.commit(); con.close()
        r = self.c.get("/paciente/", follow_redirects=True)
        self.assertIn("Iniciar sesión", self.html(r))

    def test_registro_paciente_publico(self):
        self.c.get("/registro")
        r = self.post("/registro", {"nombre": "Laura Gomez", "documento": "555666777", "telefono": "3101234567",
                                    "correo": "laura@correo.com", "password": "clave123", "password2": "clave123"})
        self.assertIn("Registro exitoso", self.html(r))
        r = self.login("laura@correo.com", "clave123")
        self.assertIn("Portal del paciente", self.html(r))
        # validaciones (con otro cliente sin sesión)
        self.c = self.app.test_client()
        self.c.get("/registro")
        r = self.post("/registro", {"nombre": "A", "documento": "12", "telefono": "1", "correo": "x",
                                    "password": "123", "password2": "456"})
        for m in ["nombre debe tener", "documento debe tener", "teléfono debe tener", "correo electrónico no es válido",
                  "al menos 6", "no coinciden"]:
            self.assertIn(m, self.html(r))

    def test_404_y_pagina_error(self):
        r = self.c.get("/no-existe")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Página no encontrada", self.html(r))


class TestAdmin(Base):
    def setUp(self):
        super().setUp()
        self.login("admin@citas.com", "admin123")

    def test_dashboard_reporte_filtros_csv(self):
        r = self.c.get("/admin/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("chart-data", self.html(r))
        r = self.c.get("/admin/?estado=Atendida&partial=1")
        self.assertIn("Chequeo general inicial", self.html(r))
        self.assertNotIn("Control cardiovascular", self.html(r))
        r = self.c.get("/admin/?periodo=proximos7&partial=1")
        self.assertEqual(r.status_code, 200)
        r = self.c.get("/admin/?periodo=rango&desde=2000-01-01&hasta=2000-01-02&partial=1")
        self.assertIn("No hay citas", self.html(r))
        r = self.c.get("/admin/?q=sofia&partial=1")
        self.assertIn("Dra. Sofia", self.html(r))
        r = self.c.get("/admin/reporte.csv?estado=Pendiente")
        self.assertEqual(r.mimetype, "text/csv")
        lineas = self.html(r).strip().splitlines()
        self.assertTrue(lineas[0].lstrip("\ufeff").startswith("ID,Fecha"))
        self.assertEqual(len(lineas) - 1, 3)

    def test_crud_usuarios_y_horarios(self):
        esp = self.q("SELECT id FROM especialidades WHERE nombre='Pediatría'")[0]["id"]
        r = self.post("/admin/usuarios/nuevo", {"rol": "profesional", "nombre": "Dr. Luis Mora", "documento": "700700700",
                      "telefono": "3112223344", "correo": "luis@citas.com", "password": "medico123",
                      "password2": "medico123", "especialidad_id": esp})
        self.assertIn("Horario de atención", self.html(r))
        pid = self.uid("luis@citas.com")
        # bloque de horario
        r = self.post(f"/admin/profesionales/{pid}/horarios", {"dia_semana": 0, "hora_inicio": "08:00", "hora_fin": "12:00"})
        self.assertIn("Bloque de atención agregado", self.html(r))
        r = self.post(f"/admin/profesionales/{pid}/horarios", {"dia_semana": 0, "hora_inicio": "11:00", "hora_fin": "13:00"})
        self.assertIn("se cruza", self.html(r))
        r = self.post(f"/admin/profesionales/{pid}/horarios", {"dia_semana": 0, "hora_inicio": "12:00", "hora_fin": "10:00"})
        self.assertIn("posterior", self.html(r))
        hid = self.q("SELECT id FROM horarios WHERE profesional_id=?", (pid,))[0]["id"]
        r = self.post(f"/admin/profesionales/{pid}/horarios/{hid}/eliminar")
        self.assertIn("eliminado", self.html(r))
        # duplicado
        r = self.post("/admin/usuarios/nuevo", {"rol": "paciente", "nombre": "Otro", "documento": "700700700",
                      "telefono": "", "correo": "luis@citas.com", "password": "abcdef", "password2": "abcdef"})
        self.assertIn("documento ya está registrado", self.html(r))
        self.assertIn("correo ya está registrado", self.html(r))
        # editar
        r = self.post(f"/admin/usuarios/{pid}/editar", {"nombre": "Dr. Luis M. Mora", "documento": "700700700",
                      "telefono": "3112223344", "correo": "luis@citas.com", "password": "", "especialidad_id": esp})
        self.assertIn("actualizado correctamente", self.html(r))
        self.assertEqual(self.q("SELECT nombre FROM usuarios WHERE id=?", (pid,))[0]["nombre"], "Dr. Luis M. Mora")
        # búsqueda dinámica
        r = self.c.get("/admin/usuarios?q=luis&partial=1")
        self.assertIn("Luis M. Mora", self.html(r))
        self.assertNotIn("Carlos Administrador", self.html(r))
        # desactivar / eliminar
        r = self.post(f"/admin/usuarios/{pid}/estado")
        self.assertEqual(self.q("SELECT activo FROM usuarios WHERE id=?", (pid,))[0]["activo"], 0)
        r = self.post(f"/admin/usuarios/{pid}/eliminar")
        self.assertIn("Usuario eliminado", self.html(r))

    def test_no_eliminar_con_citas_ni_a_si_mismo(self):
        r = self.post(f"/admin/usuarios/{self.uid('medico@citas.com')}/eliminar")
        self.assertIn("citas asociadas", self.html(r))
        r = self.post(f"/admin/usuarios/{self.uid('admin@citas.com')}/eliminar")
        self.assertIn("propia cuenta", self.html(r))

    def test_especialidades_crud(self):
        r = self.post("/admin/especialidades", {"nombre": "Neurología"})
        self.assertIn("Especialidad creada", self.html(r))
        r = self.post("/admin/especialidades", {"nombre": "Neurología"})
        self.assertIn("ya existe", self.html(r))
        eid = self.q("SELECT id FROM especialidades WHERE nombre='Neurología'")[0]["id"]
        r = self.post(f"/admin/especialidades/{eid}/editar", {"nombre": "Neurocirugía"})
        self.assertIn("actualizada", self.html(r))
        r = self.post(f"/admin/especialidades/{eid}/eliminar")
        self.assertIn("eliminada", self.html(r))
        usada = self.q("SELECT id FROM especialidades WHERE nombre='Cardiología'")[0]["id"]
        r = self.post(f"/admin/especialidades/{usada}/eliminar")
        self.assertIn("no se puede eliminar", self.html(r))

    def test_recordatorios_manana_demo(self):
        f, h = dia_habil(1)
        manana = (date.today() + timedelta(days=1)).isoformat()
        import sqlite3
        con = sqlite3.connect(self.path)
        con.execute("UPDATE citas SET fecha=? WHERE estado='Pendiente'", (manana,)); con.commit(); con.close()
        r = self.post("/admin/recordatorios/enviar-manana")
        self.assertIn("3 enviados", self.html(r))
        r = self.post("/admin/recordatorios/enviar-manana")      # no repite
        self.assertIn("0 enviados", self.html(r))
        self.assertEqual(len(self.q("SELECT * FROM recordatorios WHERE modo='demo'")), 3)


class TestRecepcion(Base):
    def setUp(self):
        super().setUp()
        self.login("recepcion@citas.com", "recep123")

    def test_crud_pacientes(self):
        r = self.post("/recepcion/pacientes/nuevo", {"nombre": "Pedro Ruiz", "documento": "909090909",
                      "telefono": "3201112233", "correo": "pedro@correo.com", "password": ""})
        self.assertIn("Contraseña temporal", self.html(r))
        pid = self.uid("pedro@correo.com")
        r = self.post(f"/recepcion/pacientes/{pid}/editar", {"nombre": "Pedro Ruiz M", "documento": "909090909",
                      "telefono": "3201112233", "correo": "pedro@correo.com", "password": ""})
        self.assertIn("actualizados", self.html(r))
        r = self.c.get("/recepcion/pacientes?q=pedro&partial=1")
        self.assertIn("Pedro Ruiz M", self.html(r))
        self.assertNotIn("Maria Paciente", self.html(r))
        r = self.post(f"/recepcion/pacientes/{pid}/eliminar")
        self.assertIn("Paciente eliminado", self.html(r))
        # con citas no se elimina
        r = self.post(f"/recepcion/pacientes/{self.uid('paciente@citas.com')}/eliminar")
        self.assertIn("tiene citas", self.html(r))

    def test_agendar_valida_cruces_horario_y_pasado(self):
        pac, prof = self.uid("juan@citas.com"), self.uid("medico@citas.com")
        f, _ = dia_habil(5)
        ok = self.post("/recepcion/citas/nueva", {"paciente_id": pac, "profesional_id": prof, "fecha": f,
                       "hora": "14:00", "motivo": "Control"})
        self.assertIn("sin cruces de horario", self.html(ok))
        self.assertIn("MODO DEMOSTRACIÓN", self.html(ok))
        # cruce profesional
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.uid("paciente@citas.com"), "profesional_id": prof,
                      "fecha": f, "hora": "14:00", "motivo": "x"})
        self.assertIn("profesional ya tiene una cita", self.html(r))
        # cruce paciente con otro profesional
        r = self.post("/recepcion/citas/nueva", {"paciente_id": pac, "profesional_id": self.uid("sofia@citas.com"),
                      "fecha": f, "hora": "14:00", "motivo": "x"})
        self.assertIn("paciente ya tiene otra cita", self.html(r))
        # fuera de horario (13:00 es hora de almuerzo) y fin de semana
        r = self.post("/recepcion/citas/nueva", {"paciente_id": pac, "profesional_id": prof, "fecha": f,
                      "hora": "13:00", "motivo": "x"})
        self.assertIn("no atiende", self.html(r))
        d = date.today()
        while d.weekday() != 5 or d <= date.today():
            d += timedelta(days=1)
        r = self.post("/recepcion/citas/nueva", {"paciente_id": pac, "profesional_id": prof, "fecha": d.isoformat(),
                      "hora": "09:00", "motivo": "x"})
        self.assertIn("no atiende", self.html(r))
        # pasado
        r = self.post("/recepcion/citas/nueva", {"paciente_id": pac, "profesional_id": prof,
                      "fecha": (date.today() - timedelta(days=1)).isoformat(), "hora": "09:00", "motivo": "x"})
        self.assertIn("futuras", self.html(r))
        # un cancelado libera el horario
        cid = self.q("SELECT id FROM citas WHERE fecha=? AND hora='14:00:00'", (f,))[0]["id"]
        self.post(f"/recepcion/citas/{cid}/estado", {"estado": "Cancelada"})
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.uid("paciente@citas.com"), "profesional_id": prof,
                      "fecha": f, "hora": "14:00", "motivo": "reuso"})
        self.assertIn("sin cruces de horario", self.html(r))

    def test_editar_estado_recordatorio_eliminar_cita(self):
        c = self.q("SELECT * FROM citas WHERE estado='Pendiente' ORDER BY id LIMIT 1")[0]
        f, _ = dia_habil(6)
        r = self.post(f"/recepcion/citas/{c['id']}/editar", {"paciente_id": c["paciente_id"], "profesional_id": c["profesional_id"],
                      "fecha": f, "hora": "10:00", "motivo": "Reprogramada por recepción"})
        self.assertIn("Cita actualizada", self.html(r))
        r = self.get_form(c["id"])
        self.assertIn(f, r)
        # B6 (adaptada): recepción no atiende, solo cancela
        r = self.post(f"/recepcion/citas/{c['id']}/estado", {"estado": "Atendida"})
        self.assertIn("Recepción solo puede cancelar", self.html(r))
        self.assertEqual(self.q("SELECT estado FROM citas WHERE id=?", (c["id"],))[0]["estado"], "Pendiente")
        r = self.post(f"/recepcion/citas/{c['id']}/estado", {"estado": "Inventado"})
        self.assertEqual(r.status_code, 400)
        r = self.post(f"/recepcion/citas/{c['id']}/recordatorio")
        self.assertIn("MODO DEMOSTRACIÓN", self.html(r))
        self.assertEqual(len(self.q("SELECT * FROM recordatorios WHERE cita_id=?", (c["id"],))), 1)
        r = self.post(f"/recepcion/citas/{c['id']}/eliminar")
        self.assertIn("Cita eliminada", self.html(r))
        # con nota clínica no se elimina
        atendida = self.q("SELECT id FROM citas WHERE estado='Atendida' AND id IN (SELECT cita_id FROM historial_citas)")[0]["id"]
        r = self.post(f"/recepcion/citas/{atendida}/eliminar")
        self.assertIn("notas clínicas", self.html(r))

    def get_form(self, cid):
        return self.html(self.c.get(f"/recepcion/citas/{cid}/editar"))

    def test_filtros_dinamicos_citas(self):
        r = self.c.get("/recepcion/citas?estado=Atendida&partial=1")
        self.assertIn("Chequeo general inicial", self.html(r))
        self.assertNotIn("<html", self.html(r))
        r = self.c.get("/recepcion/citas?q=juan&partial=1")
        self.assertIn("Juan Perez", self.html(r))

    def test_dashboard_y_formulario(self):
        self.assertEqual(self.c.get("/recepcion/").status_code, 200)
        self.assertEqual(self.c.get("/recepcion/citas/nueva?paciente_id=5").status_code, 200)
        self.assertEqual(self.c.get("/recepcion/pacientes").status_code, 200)


class TestProfesional(Base):
    def setUp(self):
        super().setUp()
        self.login("medico@citas.com", "medico123")

    def test_agenda_y_estados(self):
        r = self.c.get(f"/profesional/?fecha={dia_habil(1)[0]}")
        self.assertIn("Control cardiovascular", self.html(r))
        mia_c = self.q("SELECT id, fecha FROM citas WHERE profesional_id=? AND estado='Pendiente'", (self.uid("medico@citas.com"),))[0]
        mia = mia_c["id"]
        with self.reloj(mia_c["fecha"], "09:10"):     # B5 (adaptada): se atiende el día de la cita, dentro del bloque
            r = self.post(f"/profesional/citas/{mia}/estado", {"estado": "Atendida"})
        self.assertIn("marcada como", self.html(r))
        ajena = self.q("SELECT id FROM citas WHERE profesional_id=?", (self.uid("sofia@citas.com"),))[0]["id"]
        self.assertEqual(self.post(f"/profesional/citas/{ajena}/estado", {"estado": "Atendida"}).status_code, 403)
        self.assertEqual(self.post(f"/profesional/citas/{mia}/estado", {"estado": "Cancelada"}).status_code, 400)
        r = self.c.get("/profesional/?q=maria&partial=1")
        self.assertIn("Maria Paciente", self.html(r))

    def test_historial_crud_y_permisos(self):
        pac = self.uid("paciente@citas.com")
        fila = self.q("SELECT id, fecha FROM citas WHERE profesional_id=? AND paciente_id=?", (self.uid("medico@citas.com"), pac))[0]
        with self.reloj(fila["fecha"], "09:10"):      # B5 (adaptada): notas solo el día de la cita, dentro del bloque
            self._historial_crud_y_permisos(pac, fila["id"])

    def _historial_crud_y_permisos(self, pac, cita):
        r = self.post(f"/profesional/pacientes/{pac}/historial/agregar", {"cita_id": cita, "observacion": "Presión normal, continuar tratamiento."})
        self.assertIn("Nota clínica agregada", self.html(r))
        nid = self.q("SELECT id FROM historial_citas WHERE observacion LIKE 'Presión%'")[0]["id"]
        r = self.post(f"/profesional/historial/{nid}/editar", {"observacion": "Presión normal. Control en un mes."})
        self.assertIn("Nota actualizada", self.html(r))
        self.assertIn("Control en un mes", self.html(self.c.get(f"/profesional/pacientes/{pac}/historial")))
        r = self.post(f"/profesional/pacientes/{pac}/historial/agregar", {"cita_id": cita, "observacion": "ab"})
        self.assertIn("al menos 5", self.html(r))
        # nota de otro médico: no editable
        ajena = self.q("SELECT id FROM historial_citas WHERE registrado_por=?", (self.uid("sofia@citas.com"),))[0]["id"]
        self.assertEqual(self.post(f"/profesional/historial/{ajena}/editar", {"observacion": "hackeo de nota"}).status_code, 403)
        self.assertEqual(self.post(f"/profesional/historial/{ajena}/eliminar").status_code, 403)
        # A6: anular exige motivo; la nota no se borra físicamente
        r = self.post(f"/profesional/historial/{nid}/eliminar")
        self.assertIn("motivo de la anulación", self.html(r))
        r = self.post(f"/profesional/historial/{nid}/eliminar", {"motivo": "Registrada en el paciente equivocado"})
        self.assertIn("Nota eliminada", self.html(r))

    def test_historial_paciente_ajeno_403(self):
        # crear paciente sin citas con este médico
        import sqlite3
        from app.models.usuario import hash_password
        con = sqlite3.connect(self.path)
        con.execute("INSERT INTO usuarios (nombre,documento,correo,password_hash,rol) VALUES ('Nuevo','123123123','n@n.com',?,'paciente')",
                    (hash_password("abcdef"),))
        con.commit(); con.close()
        self.assertEqual(self.c.get(f"/profesional/pacientes/{self.uid('n@n.com')}/historial").status_code, 403)


class TestPaciente(Base):
    def setUp(self):
        super().setUp()
        self.login("paciente@citas.com", "paciente123")
        self.pid = self.uid("paciente@citas.com")

    def test_solicitar_reprogramar_cancelar(self):
        prof = self.uid("sofia@citas.com")
        f, _ = dia_habil(7)
        r = self.post("/paciente/citas/solicitar", {"profesional_id": prof, "fecha": f, "hora": "11:00", "motivo": "Dolor de espalda"})
        self.assertIn("Cita solicitada exitosamente", self.html(r))
        self.assertEqual(len(self.q("SELECT * FROM recordatorios WHERE tipo='confirmacion'")), 1)
        cid = self.q("SELECT id FROM citas WHERE motivo='Dolor de espalda'")[0]["id"]
        # mismo horario ocupado
        r = self.post("/paciente/citas/solicitar", {"profesional_id": prof, "fecha": f, "hora": "11:00", "motivo": "Otro motivo"})
        self.assertIn("ya tiene una cita", self.html(r))
        # reprogramar
        f2, _ = dia_habil(8)
        r = self.post(f"/paciente/citas/{cid}/reprogramar", {"nueva_fecha": f2, "nueva_hora": "15:30"})
        self.assertIn("reprogramada exitosamente", self.html(r))
        self.assertEqual(self.q("SELECT fecha,hora FROM citas WHERE id=?", (cid,))[0]["hora"], "15:30:00")
        # cancelar
        r = self.post(f"/paciente/citas/{cid}/cancelar")
        self.assertIn("fue cancelada", self.html(r))
        r = self.post(f"/paciente/citas/{cid}/cancelar")
        self.assertIn("Solo se pueden cancelar citas pendientes", self.html(r))

    def test_anticipacion_minima(self):
        prof = self.uid("medico@citas.com")
        ahora = datetime.now() + timedelta(minutes=30)
        import sqlite3
        con = sqlite3.connect(self.path)
        cur = con.execute("INSERT INTO citas (paciente_id,profesional_id,fecha,hora,estado,motivo) VALUES (?,?,?,?,'Pendiente','Pronta')",
                          (self.pid, prof, ahora.date().isoformat(), ahora.strftime("%H:%M:00")))
        cid = cur.lastrowid; con.commit(); con.close()
        r = self.post(f"/paciente/citas/{cid}/cancelar")
        self.assertIn("horas de anticipación", self.html(r))
        self.assertEqual(self.q("SELECT estado FROM citas WHERE id=?", (cid,))[0]["estado"], "Pendiente")

    def test_no_toca_citas_ajenas(self):
        ajena = self.q("SELECT id FROM citas WHERE paciente_id<>?", (self.pid,))[0]["id"]
        self.assertEqual(self.post(f"/paciente/citas/{ajena}/cancelar").status_code, 404)
        self.assertEqual(self.post(f"/paciente/citas/{ajena}/reprogramar", {"nueva_fecha": "2030-01-01", "nueva_hora": "09:00"}).status_code, 404)
        self.assertEqual(self.post(f"/paciente/recordatorio/{ajena}").status_code, 404)

    def test_recordatorio_demo_y_dashboard(self):
        cid = self.q("SELECT id FROM citas WHERE paciente_id=? AND estado='Pendiente'", (self.pid,))[0]["id"]
        r = self.post(f"/paciente/recordatorio/{cid}")
        self.assertIn("MODO DEMOSTRACIÓN", self.html(r))
        self.assertIn("Recordatorio de cita médica", self.html(r))   # aparece en notificaciones

    def test_perfil_y_cambio_password(self):
        base = {"nombre": "Maria G. Gomez", "telefono": "3004445566", "correo": "paciente@citas.com"}
        r = self.post("/paciente/perfil", {**base, "password": "nueva123", "password2": "nueva123", "password_actual": "incorrecta"})
        self.assertIn("contraseña actual no es correcta", self.html(r))
        r = self.post("/paciente/perfil", {**base, "password": "nueva123", "password2": "nueva123", "password_actual": "paciente123"})
        self.assertIn("datos fueron actualizados", self.html(r))
        self.post("/logout")
        self.assertIn("Portal del paciente", self.html(self.login("paciente@citas.com", "nueva123")))

    def test_api_disponibilidad(self):
        prof = self.uid("medico@citas.com")
        f, _ = dia_habil(1)
        d = self.c.get(f"/api/disponibilidad?profesional_id={prof}&fecha={f}").get_json()
        self.assertIn("08:00", d["slots"]); self.assertNotIn("09:00", d["slots"])   # 09:00 ocupado por seed
        self.assertNotIn("12:00", d["slots"]); self.assertNotIn("13:30", d["slots"])
        self.assertIn("14:00", d["slots"]); self.assertEqual(d["slots"][-1], "16:30")
        sab = date.today()
        while sab.weekday() != 5:
            sab += timedelta(days=1)
        d = self.c.get(f"/api/disponibilidad?profesional_id={prof}&fecha={sab}").get_json()
        self.assertEqual(d["slots"], []); self.assertIn("no atiende", d["mensaje"])
        self.assertEqual(self.c.get("/api/disponibilidad").get_json()["slots"], [])
        anon = self.app.test_client()
        self.assertEqual(anon.get("/api/disponibilidad").status_code, 302)


class TestCorreoReal(Base):
    """Verifica la ruta de envío SMTP real (con smtplib simulado)."""
    def test_envio_smtp(self):
        self.app.config.update(MAIL_SERVER="smtp.ejemplo.com", MAIL_PORT=587, MAIL_USER="u", MAIL_PASSWORD="p", MAIL_USE_TLS=True)
        self.login("recepcion@citas.com", "recep123")
        cid = self.q("SELECT id FROM citas WHERE estado='Pendiente'")[0]["id"]
        with mock.patch("smtplib.SMTP") as smtp:
            r = self.post(f"/recepcion/citas/{cid}/recordatorio")
            srv = smtp.return_value
            smtp.assert_called_once_with("smtp.ejemplo.com", 587, timeout=20)
            srv.starttls.assert_called_once(); srv.login.assert_called_once_with("u", "p")
            self.assertEqual(srv.send_message.call_count, 1)
            msg = srv.send_message.call_args[0][0]
            self.assertEqual(msg["To"], "paciente@citas.com")
            self.assertIn("Recordatorio", msg["Subject"])
        self.assertIn("Correo enviado a", self.html(r))
        self.assertEqual(self.q("SELECT modo FROM recordatorios")[0]["modo"], "smtp")

    def test_fallo_smtp_se_registra(self):
        self.app.config.update(MAIL_SERVER="smtp.ejemplo.com")
        self.login("recepcion@citas.com", "recep123")
        cid = self.q("SELECT id FROM citas WHERE estado='Pendiente'")[0]["id"]
        with mock.patch("smtplib.SMTP", side_effect=OSError("sin red")):
            r = self.post(f"/recepcion/citas/{cid}/recordatorio")
        self.assertIn("No se pudo enviar", self.html(r))
        self.assertEqual(self.q("SELECT modo FROM recordatorios")[0]["modo"], "error")


class TestBD(unittest.TestCase):
    def test_mysql_sin_servidor_muestra_pagina_amigable(self):
        class Cfg(Config):
            TESTING = True
            DB_ENGINE = "mysql"
            DB_HOST = "127.0.0.1"
            DB_PORT = 1
        app = create_app(Cfg)
        r = app.test_client().post("/login", data={})
        # sin CSRF responde 400 antes de tocar la BD; con GET a una ruta que sí consulta:
        c = app.test_client()
        with c.session_transaction() as s:
            s["user_id"], s["rol"] = 1, "administrador"
        r = c.get("/admin/")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Base de datos no disponible", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
