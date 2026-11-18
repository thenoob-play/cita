"""Pruebas de Mi cuenta, centro de notificaciones, barra lateral y exportaciones."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_app import Base, dia_habil  # noqa: E402


class TestLayout(Base):
    def test_barra_lateral_por_rol(self):
        r = self.login("recepcion@citas.com", "recep123")
        h = self.html(r)
        self.assertIn('class="sidebar"', h)
        self.assertIn("Agendar cita", h)
        self.assertIn("Mi cuenta", h)
        self.assertIn('data-notif-count', h)
        self.assertNotIn("Especialidades", h)        # solo para administrador

    def test_login_sin_barra_lateral(self):
        h = self.html(self.c.get("/login"))
        self.assertNotIn('class="sidebar"', h)
        self.assertIn("sin-sesion", h)


class TestNotificaciones(Base):
    def setUp(self):
        super().setUp()
        self.pac, self.prof = self.uid("paciente@citas.com"), self.uid("medico@citas.com")

    def _notifs(self, uid):
        return self.q("SELECT * FROM notificaciones WHERE usuario_id=? ORDER BY id", (uid,))

    def test_recepcion_agenda_notifica_a_paciente_y_profesional(self):
        self.login("recepcion@citas.com", "recep123")
        f, _ = dia_habil(2)
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.pac, "profesional_id": self.prof,
                                                  "fecha": f, "hora": "08:00", "motivo": "Control"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._notifs(self.pac)[-1]["titulo"], "Nueva cita programada")
        self.assertEqual(self._notifs(self.prof)[-1]["titulo"], "Nueva cita programada")
        self.assertNotIn("Control", self._notifs(self.pac)[-1]["mensaje"])   # sin motivo de consulta

    def test_paciente_solicita_notifica_solo_al_profesional(self):
        self.login("paciente@citas.com", "paciente123")
        f, _ = dia_habil(2)
        self.post("/paciente/citas/solicitar", {"profesional_id": self.prof, "fecha": f, "hora": "08:00",
                                                "motivo": "Dolor"})
        self.assertEqual(len(self._notifs(self.pac)), 0)       # el actor no se notifica a sí mismo
        self.assertEqual(len(self._notifs(self.prof)), 1)

    def test_campana_resumen_leer_y_eliminar(self):
        self.login("recepcion@citas.com", "recep123")
        cid = self.q("SELECT id FROM citas WHERE paciente_id=? AND estado='Pendiente'", (self.pac,))[0]["id"]
        self.post(f"/recepcion/citas/{cid}/estado", {"estado": "Cancelada"})
        self.post("/logout")
        r = self.login("paciente@citas.com", "paciente123")
        self.assertIn("Cita cancelada", self.html(r))           # aparece en la campana
        d = self.c.get("/notificaciones/resumen").get_json()
        self.assertEqual(d["no_leidas"], 1)
        nid = d["items"][0]["id"]
        r = self.post(f"/notificaciones/{nid}/abrir", follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/paciente", r.headers["Location"])
        self.assertEqual(self.c.get("/notificaciones/resumen").get_json()["no_leidas"], 0)
        self.post("/notificaciones/limpiar")
        self.assertEqual(len(self._notifs(self.pac)), 0)

    def test_no_puede_tocar_notificaciones_ajenas(self):
        self.login("recepcion@citas.com", "recep123")
        f, _ = dia_habil(2)
        self.post("/recepcion/citas/nueva", {"paciente_id": self.pac, "profesional_id": self.prof,
                                              "fecha": f, "hora": "08:00", "motivo": "Control"})
        nid = self._notifs(self.pac)[-1]["id"]
        self.assertEqual(self.post(f"/notificaciones/{nid}/abrir", follow=False).status_code, 404)
        self.assertEqual(self.post(f"/notificaciones/{nid}/eliminar", follow=False).status_code, 404)
        self.assertEqual(len(self._notifs(self.pac)), 1)

    def test_leer_todas_por_fetch(self):
        self.login("recepcion@citas.com", "recep123")
        f, _ = dia_habil(2)
        self.post("/recepcion/citas/nueva", {"paciente_id": self.pac, "profesional_id": self.prof,
                                              "fecha": f, "hora": "08:00", "motivo": "Control"})
        self.post("/logout")
        self.login("paciente@citas.com", "paciente123")
        r = self.c.post("/notificaciones/leer-todas",
                        headers={"X-CSRF-Token": self.tok(), "X-Requested-With": "fetch"})
        self.assertEqual(r.get_json()["no_leidas"], 0)
        self.assertIn("No tiene notificaciones sin leer", self.html(self.c.get("/notificaciones?filtro=no_leidas")))


class TestCuenta(Base):
    def test_cuenta_para_todos_los_roles(self):
        for correo, pw in [("admin@citas.com", "admin123"), ("recepcion@citas.com", "recep123"),
                           ("medico@citas.com", "medico123"), ("paciente@citas.com", "paciente123")]:
            c = self.app.test_client()
            self.login(correo, pw, c)
            h = self.html(c.get("/cuenta"))
            self.assertIn("Mi cuenta", h, correo)
            self.assertIn(correo, h)

    def test_profesional_edita_datos_sin_perder_especialidad(self):
        self.login("medico@citas.com", "medico123")
        esp = self.q("SELECT especialidad_id FROM usuarios WHERE correo='medico@citas.com'")[0]["especialidad_id"]
        r = self.post("/cuenta/perfil", {"nombre": "Dr. Nuevo Nombre", "telefono": "3001112233",
                                         "correo": "medico@citas.com", "especialidad_id": "999"})
        self.assertIn("datos fueron actualizados", self.html(r))
        u = self.q("SELECT nombre, especialidad_id FROM usuarios WHERE correo='medico@citas.com'")[0]
        self.assertEqual((u["nombre"], u["especialidad_id"]), ("Dr. Nuevo Nombre", esp))

    def test_cambio_password_y_notificacion(self):
        self.login("recepcion@citas.com", "recep123")
        r = self.post("/cuenta/password", {"password_actual": "mala", "password": "otra123", "password2": "otra123"})
        self.assertIn("contraseña actual no es correcta", self.html(r))
        r = self.post("/cuenta/password", {"password_actual": "recep123", "password": "otra123", "password2": "otra123"})
        self.assertIn("Contraseña actualizada", self.html(r))
        self.post("/logout")
        self.assertIn("Panel de recepción", self.html(self.login("recepcion@citas.com", "otra123")))

    def test_ultimo_acceso_y_actividad(self):
        self.login("admin@citas.com", "admin123")
        self.assertIsNotNone(self.q("SELECT ultimo_acceso FROM usuarios WHERE correo='admin@citas.com'")[0]["ultimo_acceso"])
        self.post("/logout")
        self.login("admin@citas.com", "admin123")
        self.assertNotIn("Primer ingreso", self.html(self.c.get("/cuenta")))

    def test_exportar_mis_datos(self):
        self.login("paciente@citas.com", "paciente123")
        r = self.c.get("/cuenta/mis-datos.json")
        d = json.loads(r.get_data(as_text=True))
        self.assertEqual(d["perfil"]["correo"], "paciente@citas.com")
        self.assertNotIn("password_hash", d["perfil"])
        self.assertTrue(d["citas"])

    def test_perfil_antiguo_redirige(self):
        self.login("paciente@citas.com", "paciente123")
        r = self.c.get("/paciente/perfil")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/cuenta", r.headers["Location"])


class TestCalendario(Base):
    def test_ics_de_cita_propia(self):
        self.login("paciente@citas.com", "paciente123")
        pac = self.uid("paciente@citas.com")
        cid = self.q("SELECT id FROM citas WHERE paciente_id=? AND estado='Pendiente'", (pac,))[0]["id"]
        r = self.c.get(f"/paciente/citas/{cid}/calendario.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/calendar", r.headers["Content-Type"])
        self.assertIn("BEGIN:VEVENT", self.html(r))
        otra = self.q("SELECT id FROM citas WHERE paciente_id<>? LIMIT 1", (pac,))[0]["id"]
        self.assertEqual(self.c.get(f"/paciente/citas/{otra}/calendario.ics").status_code, 404)


if __name__ == "__main__":
    unittest.main()
