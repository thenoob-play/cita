"""Pruebas de la Fase A (correcciones de la revisión). Ejecutar:  python -m unittest discover -s tests -v"""
import re
import sqlite3
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import os as _os, sys as _sys  # permite ejecutar este archivo sin 'discover -s tests'
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from test_app import Base, TestConfig, dia_habil  # noqa: F401  (Base no tiene pruebas propias)

from app import ConfiguracionInsegura, create_app

BOGOTA = ZoneInfo("America/Bogota")


@contextmanager
def reloj(local_dt):
    """Congela el reloj del negocio en `local_dt` (hora de Bogotá, sin tzinfo)."""
    utc = local_dt.replace(tzinfo=BOGOTA).astimezone(timezone.utc)
    with mock.patch("app.utils._utcnow", return_value=utc):
        yield


class TestDobleReserva(Base):
    """A1 · Restricciones de BD contra doble reserva."""

    def test_indices_unicos_impiden_doble_reserva_directa(self):
        c = self.q("SELECT * FROM citas WHERE estado='Pendiente' LIMIT 1")[0]
        con = sqlite3.connect(self.path)
        otro_pac = self.uid("juan@citas.com") if c["paciente_id"] != self.uid("juan@citas.com") else self.uid("paciente@citas.com")
        with self.assertRaises(sqlite3.IntegrityError):    # mismo profesional, fecha y hora
            con.execute("INSERT INTO citas (paciente_id, profesional_id, fecha, hora) VALUES (?,?,?,?)",
                        (otro_pac, c["profesional_id"], c["fecha"], c["hora"]))
        with self.assertRaises(sqlite3.IntegrityError):    # mismo paciente, fecha y hora
            con.execute("INSERT INTO citas (paciente_id, profesional_id, fecha, hora) VALUES (?,?,?,?)",
                        (c["paciente_id"], self.uid("sofia@citas.com"), c["fecha"], c["hora"]))
        # una cita cancelada no ocupa el horario
        con.execute("INSERT INTO citas (paciente_id, profesional_id, fecha, hora, estado) VALUES (?,?,?,?, 'Cancelada')",
                    (otro_pac, c["profesional_id"], c["fecha"], c["hora"]))
        con.commit(); con.close()

    def test_doble_reserva_concurrente_la_impide_la_bd(self):
        """Simula la carrera: la validación de la app no ve la otra cita, la BD sí."""
        self.login("recepcion@citas.com", "recep123")
        f, _ = dia_habil(5)
        prof, p1, p2 = self.uid("medico@citas.com"), self.uid("juan@citas.com"), self.uid("paciente@citas.com")
        r = self.post("/recepcion/citas/nueva", {"paciente_id": p1, "profesional_id": prof, "fecha": f, "hora": "10:00"})
        self.assertIn("sin cruces de horario", self.html(r))
        with mock.patch("app.models.cita.cruce", return_value=None):   # la otra transacción "aún no se veía"
            r = self.post("/recepcion/citas/nueva", {"paciente_id": p2, "profesional_id": prof, "fecha": f, "hora": "10:00"})
        self.assertIn("acaba de ser reservado", self.html(r))
        self.assertEqual(len(self.q("SELECT id FROM citas WHERE fecha=? AND hora='10:00:00'", (f,))), 1)

    def test_dos_hilos_reservan_el_mismo_horario(self):
        prof, f = self.uid("medico@citas.com"), dia_habil(6)[0]
        pacientes = [self.uid("juan@citas.com"), self.uid("paciente@citas.com")]
        resultados, barrera = [], threading.Barrier(2)

        def reservar(pac):
            with self.app.test_request_context():
                from app.models import cita
                barrera.wait()
                resultados.append(cita.programar(pac, prof, f, "11:00", "Concurrente"))
        hilos = [threading.Thread(target=reservar, args=(p,)) for p in pacientes]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        exitos = [r for r in resultados if r[1] is None]
        self.assertEqual(len(exitos), 1, resultados)
        self.assertEqual(len(self.q("SELECT id FROM citas WHERE fecha=? AND hora='11:00:00'", (f,))), 1)


class TestConfiguracion(unittest.TestCase):
    """A2 · SECRET_KEY obligatoria fuera de desarrollo."""

    def _cfg(self, **kw):
        return type("Cfg", (TestConfig,), {"TESTING": False, "APP_ENV": "production", "DEV_MODE": False, **kw})

    def test_sin_secret_key_no_arranca(self):
        for clave in (None, "", "cambia-esta-clave-en-produccion", "corta"):
            with self.assertRaises(ConfiguracionInsegura):
                create_app(self._cfg(SECRET_KEY=clave))

    def test_con_secret_key_arranca_y_cookie_secure_configurable(self):
        app = create_app(self._cfg(SECRET_KEY="x" * 40, SESSION_COOKIE_SECURE=True))
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])

    def test_desarrollo_no_exige_clave(self):
        create_app(self._cfg(APP_ENV="development", DEV_MODE=True, SECRET_KEY="dev"))

    def test_run_py_sin_debug_fijo(self):
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("debug=True", src)
        self.assertIn("FLASK_DEBUG", src)


class TestDatosSensibles(Base):
    """A3/A4 · Nada sensible en la cookie de sesión; correos sin motivo."""

    def _flashes(self):
        with self.c.session_transaction() as s:
            return " ".join(str(m) for _, m in s.get("_flashes", []))

    def test_password_temporal_no_va_a_la_sesion(self):
        self.login("recepcion@citas.com", "recep123")
        r = self.post("/recepcion/pacientes/nuevo", {"nombre": "Pedro Ruiz", "documento": "909090909",
                      "telefono": "3201112233", "correo": "pedro@correo.com", "password": ""}, follow=False)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        temporal = re.search(r'id="pw-temporal">([^<]+)<', self.html(r)).group(1)
        self.assertNotIn(temporal, self._flashes())
        with self.c.session_transaction() as s:
            self.assertNotIn(temporal, repr(dict(s)))
        self.c.post("/logout", data={"_csrf": self.tok()})
        self.assertIn("Portal del paciente", self.html(self.login("pedro@correo.com", temporal)))

    def test_correo_demo_no_va_al_flash_y_no_incluye_motivo(self):
        self.login("recepcion@citas.com", "recep123")
        c = self.q("SELECT * FROM citas WHERE estado='Pendiente' ORDER BY id LIMIT 1")[0]
        self.post(f"/recepcion/citas/{c['id']}/recordatorio", follow=False)
        flashes = self._flashes()
        self.assertIn("MODO DEMOSTRACIÓN", flashes)
        self.assertNotIn("Estimado", flashes)
        self.assertNotIn(c["motivo"], flashes)
        reg = self.q("SELECT * FROM recordatorios WHERE cita_id=?", (c["id"],))[0]
        self.assertNotIn(c["motivo"], reg["mensaje"])
        self.assertIn("Profesional:", reg["mensaje"])
        # vista previa: recepción sí; un paciente ajeno no
        self.assertEqual(self.c.get(f"/correos/{reg['id']}").status_code, 200)
        otro = self.app.test_client()
        ajeno = "juan@citas.com" if self.uid("paciente@citas.com") == c["paciente_id"] else "paciente@citas.com"
        self.login(ajeno, "paciente123", otro)
        self.assertEqual(otro.get(f"/correos/{reg['id']}").status_code, 404)

    def test_envio_en_segundo_plano_no_bloquea(self):
        self.app.config.update(MAIL_ASYNC=True, MAIL_SERVER="smtp.ejemplo.com")
        self.login("admin@citas.com", "admin123")
        manana = (datetime.now(BOGOTA).date() + timedelta(days=1)).isoformat()
        con = sqlite3.connect(self.path)
        con.execute("UPDATE citas SET fecha=? WHERE estado='Pendiente'", (manana,)); con.commit(); con.close()

        def lento(*a, **k):
            time.sleep(0.6)
            return mock.MagicMock()
        with mock.patch("smtplib.SMTP", side_effect=lento):
            t0 = time.monotonic()
            r = self.post("/admin/recordatorios/enviar-manana")
            self.assertLess(time.monotonic() - t0, 0.6 * 3, "la petición esperó a los envíos SMTP")
            self.assertIn("3 enviados a la cola", self.html(r))
            fin = time.monotonic() + 10
            while time.monotonic() < fin and self.q("SELECT id FROM recordatorios WHERE modo='pendiente'"):
                time.sleep(0.1)
        self.assertEqual(len(self.q("SELECT id FROM recordatorios WHERE modo='smtp'")), 3)


class TestHistoriaClinicaInmutable(Base):
    """A6 · Corregir y anular conservan la nota original; todo queda en auditoría."""

    def test_correccion_anulacion_y_auditoria(self):
        self.login("sofia@citas.com", "medico123")
        nota = self.q("SELECT * FROM historial_citas")[0]
        pac = self.q("SELECT paciente_id FROM citas WHERE id=?", (nota["cita_id"],))[0]["paciente_id"]
        # B5: corregir solo el día de la cita y dentro del bloque -> se ubica la cita en un día hábil a las 08:00
        f = dia_habil(2)[0]
        con = sqlite3.connect(self.path)
        con.execute("UPDATE citas SET fecha=?, hora='08:00:00' WHERE id=?", (f, nota["cita_id"])); con.commit(); con.close()
        with reloj(datetime.fromisoformat(f"{f} 08:10")):
            self._flujo(nota, pac)

    def _flujo(self, nota, pac):
        self.c.get(f"/profesional/pacientes/{pac}/historial")
        self.assertTrue(self.q("SELECT id FROM auditoria WHERE accion='leer_historial' AND entidad_id=?", (pac,)))
        self.post(f"/profesional/historial/{nota['id']}/editar", {"observacion": "Texto corregido de la nota."})
        filas = self.q("SELECT * FROM historial_citas ORDER BY id")
        self.assertEqual(filas[0]["observacion"], nota["observacion"])           # original intacta
        self.assertEqual(filas[-1]["corrige_a"], nota["id"])
        # una nota ya corregida no se vuelve a corregir
        r = self.post(f"/profesional/historial/{nota['id']}/editar", {"observacion": "Otra corrección más."})
        self.assertIn("ya tiene una corrección", self.html(r))
        self.post(f"/profesional/historial/{filas[-1]['id']}/eliminar", {"motivo": "Duplicada por error"})
        anulada = self.q("SELECT * FROM historial_citas WHERE id=?", (filas[-1]["id"],))[0]
        self.assertEqual((anulada["anulada"], anulada["motivo_anulacion"]), (1, "Duplicada por error"))
        acciones = {r["accion"] for r in self.q("SELECT accion FROM auditoria")}
        self.assertTrue({"leer_historial", "corregir_nota", "anular_nota"} <= acciones)
        # la auditoría no guarda contenido clínico
        self.assertFalse(self.q("SELECT id FROM auditoria WHERE detalle LIKE '%corregido%'"))


class TestLogin(Base):
    """A7/A8 · Límite de intentos, credenciales de prueba solo en DEV, recuperación de contraseña."""

    def test_limite_de_intentos_por_correo_e_ip(self):
        momento = datetime(2026, 3, 9, 10, 0)
        with reloj(momento):
            for _ in range(5):
                r = self.login("admin@citas.com", "mala")
                self.assertIn("incorrectos", self.html(r))
            r = self.login("admin@citas.com", "admin123")            # bloqueado aunque sea correcta
            self.assertIn("Demasiados intentos", self.html(r))
            self.assertNotIn("Panel de administración", self.html(r))
            otra_ip = self.app.test_client()
            otra_ip.environ_base["REMOTE_ADDR"] = "10.0.0.9"
            self.assertIn("Panel de administración", self.html(self.login("admin@citas.com", "admin123", otra_ip)))
        with reloj(momento + timedelta(minutes=16)):                 # pasa la ventana de 15 minutos
            self.assertIn("Panel de administración", self.html(self.login("admin@citas.com", "admin123")))

    def test_credenciales_de_prueba_solo_en_modo_dev(self):
        self.app.config["DEV_MODE"] = False
        self.assertNotIn("admin123", self.html(self.c.get("/login")))
        self.app.config["DEV_MODE"] = True
        self.assertIn("admin123", self.html(self.c.get("/login")))

    def _pedir_enlace(self, correo="paciente@citas.com"):
        self.c.get("/recuperar")
        r = self.post("/recuperar", {"correo": correo})
        m = re.search(r'href="https?://[^/]+(/restablecer/[^"]+)"', self.html(r))
        return r, (m.group(1) if m else None)

    def test_recuperacion_un_solo_uso_y_expira(self):
        self.app.config["DEV_MODE"] = False
        r, enlace = self._pedir_enlace()
        self.assertIn("Si el correo está registrado", self.html(r))
        self.assertIsNone(enlace, "fuera de desarrollo el token no se muestra")
        self.app.config["DEV_MODE"] = True
        r, enlace = self._pedir_enlace()
        self.assertIsNotNone(enlace)
        with self.c.session_transaction() as s:
            self.assertNotIn(enlace.rsplit("/", 1)[1], repr(dict(s)))
        r = self.post(enlace, {"password": "nueva456", "password2": "nueva456"})
        self.assertIn("Contraseña actualizada", self.html(r))
        self.assertIn("ya se usó o venció", self.html(self.post(enlace, {"password": "otra789", "password2": "otra789"})))
        self.assertIn("Portal del paciente", self.html(self.login("paciente@citas.com", "nueva456")))
        # vencido a los 30 minutos
        c2 = self.app.test_client()
        self.c = c2
        _, enlace = self._pedir_enlace("juan@citas.com")
        with reloj(datetime.now(BOGOTA).replace(tzinfo=None) + timedelta(minutes=31)):
            r = self.c.get(enlace, follow_redirects=True)
        self.assertIn("ya se usó o venció", self.html(r))
        # correo inexistente: misma respuesta, sin enlace
        r, enlace = self._pedir_enlace("nadie@ejemplo.com")
        self.assertIn("Si el correo está registrado", self.html(r))
        self.assertIsNone(enlace)


class TestRedireccionesYPaginacion(Base):
    """A9/A10 · next/referrer solo locales; paginación; aviso de CSV truncado."""

    def test_next_externo_se_ignora(self):
        self.login("medico@citas.com", "medico123")
        cid = self.q("SELECT id FROM citas WHERE profesional_id=?", (self.uid("medico@citas.com"),))[0]["id"]
        for malo in ("//evil.com/x", "https://evil.com", "/\\evil.com"):
            r = self.post(f"/profesional/citas/{cid}/estado", {"estado": "Pendiente", "next": malo}, follow=False)
            self.assertTrue(r.headers["Location"].endswith("/profesional/"), r.headers["Location"])
        r = self.post(f"/profesional/citas/{cid}/estado", {"estado": "Pendiente", "next": "/profesional/?fecha=2030-01-01"},
                      follow=False)
        self.assertIn("/profesional/?fecha=2030-01-01", r.headers["Location"])
        self.c = self.app.test_client()
        self.login("admin@citas.com", "admin123")
        pid = self.uid("juan@citas.com")
        r = self.c.post(f"/admin/usuarios/{pid}/estado", data={"_csrf": self.tok()},
                        headers={"Referer": "https://evil.com/robo"})
        self.assertTrue(r.headers["Location"].endswith("/admin/usuarios"))

    def test_paginacion_y_csv_truncado(self):
        self.app.config.update(PAGE_SIZE=2, REPORT_MAX_ROWS=2)
        self.login("admin@citas.com", "admin123")
        p1, p2 = self.html(self.c.get("/admin/usuarios?page=1&partial=1")), self.html(self.c.get("/admin/usuarios?page=2&partial=1"))
        self.assertIn("Página 1 de 3", p1); self.assertIn("Página 2 de 3", p2)
        self.assertNotEqual(re.findall(r'fw-semibold">([^<]+)', p1), re.findall(r'fw-semibold">([^<]+)', p2))
        self.assertIn("Página 1 de 3", self.html(self.c.get("/recepcion/citas?partial=1")))
        self.assertIn("2 registro(s)", self.html(self.c.get("/recepcion/pacientes?partial=1")))   # cabe en 1 página
        r = self.c.get("/admin/reporte.csv")
        self.assertEqual(r.headers.get("X-Reporte-Truncado"), "2")
        self.assertIn("AVISO: reporte truncado a 2 filas de 5", self.html(r))


class TestMigraciones(unittest.TestCase):
    """A11 · Migraciones versionadas e idempotentes; esquema consolidado coherente."""

    def test_migraciones_en_orden_e_idempotentes(self):
        import os
        import tempfile
        import contextlib
        import io
        from config import Config
        import init_db
        for engine in ("sqlite", "mysql"):
            versiones = [v for v, _, _ in init_db.migraciones(engine)]
            self.assertEqual(versiones, list(range(1, len(versiones) + 1)), engine)
        self.assertEqual([n for _, n, _ in init_db.migraciones("sqlite")], [n for _, n, _ in init_db.migraciones("mysql")])
        fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
        try:
            Config.DB_ENGINE, Config.SQLITE_PATH = "sqlite", path
            with contextlib.redirect_stdout(io.StringIO()):
                init_db.main(reset=True, demo=False)
                init_db.main(demo=False)          # segunda vez: no reaplica
            con = sqlite3.connect(path)
            n = con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            usuarios = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
            con.close()
            self.assertEqual(n, len(init_db.migraciones("sqlite")))
            self.assertEqual(usuarios, 0, "sin --demo no se cargan cuentas de demostración")
        finally:
            os.remove(path)

    def test_database_sqlite_sql_coincide_con_migraciones(self):
        import os
        import init_db
        from config import BASE_DIR

        def esquema(con):
            out = {}
            tablas = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                "AND name NOT LIKE 'sqlite_%'")]
            for t in tablas:
                cols = {(c[1], c[2], c[3], c[4], c[5]) for c in con.execute(f"PRAGMA table_info({t})")}
                idx = {(i[1], i[2], i[4]) for i in con.execute(f"PRAGMA index_list({t})") if i[3] != "pk"}
                out[t] = (cols, {(n, u, p) for n, u, p in idx if not n.startswith("sqlite_autoindex")})
            return out
        a = sqlite3.connect(":memory:")
        with open(os.path.join(BASE_DIR, "database_sqlite.sql"), encoding="utf-8") as f:
            a.executescript(f.read())
        b = sqlite3.connect(":memory:")
        b.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, nombre TEXT NOT NULL, "
                  "aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        for _, _, ruta in init_db.migraciones("sqlite"):
            with open(ruta, encoding="utf-8") as f:
                b.executescript(f.read())
        self.assertEqual(esquema(a), esquema(b))
        self.assertEqual(a.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                         len(init_db.migraciones("sqlite")))


if __name__ == "__main__":
    unittest.main()
