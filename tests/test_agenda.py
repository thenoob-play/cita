"""Pruebas de la Fase B: atención solo dentro del horario asignado.
El reloj del negocio se congela en el LUNES 2030-01-07 09:10 (America/Bogota) para que las pruebas
no dependan del día en que se ejecutan. Horario demo: lunes a viernes 08:00-12:00 y 14:00-17:00."""
import sqlite3
import threading
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import os as _os, sys as _sys  # permite ejecutar este archivo sin 'discover -s tests'
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from test_app import Base

HOY = "2030-01-07"          # lunes
MANANA = "2030-01-08"       # martes
MIERCOLES = "2030-01-09"
SABADO = "2030-01-12"
LUNES_SIG = "2030-01-14"


class AgendaBase(Base):
    def setUp(self):
        super().setUp()
        ctx = self.reloj(HOY, "09:10")
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.med, self.sofia = self.uid("medico@citas.com"), self.uid("sofia@citas.com")
        self.pac, self.pac2 = self.uid("paciente@citas.com"), self.uid("juan@citas.com")

    def nueva_cita(self, fecha, hora, prof=None, pac=None, estado="Pendiente"):
        con = sqlite3.connect(self.path)
        cur = con.execute("INSERT INTO citas (paciente_id, profesional_id, fecha, hora, estado, motivo) "
                          "VALUES (?,?,?,?,?, 'Prueba de agenda')", (pac or self.pac, prof or self.med, fecha,
                                                                      f"{hora}:00", estado))
        cid = cur.lastrowid
        con.commit(); con.close()
        return cid

    def como(self, correo, pw):
        self.c = self.app.test_client()
        self.login(correo, pw)

    def cita(self, cid):
        return self.q("SELECT * FROM citas WHERE id=?", (cid,))[0]

    def marcar(self, cid, estado):
        return self.html(self.post(f"/profesional/citas/{cid}/estado", {"estado": estado}))


class TestReglaDeAtencion(AgendaBase):
    def test_cita_dentro_de_bloque_se_puede_atender(self):
        cid = self.nueva_cita(HOY, "09:00")
        self.como("medico@citas.com", "medico123")
        self.assertIn("marcada como &#39;Atendida&#39;", self.marcar(cid, "Atendida"))
        self.assertEqual(self.cita(cid)["estado"], "Atendida")
        r = self.post(f"/profesional/pacientes/{self.pac}/historial/agregar", {"cita_id": cid, "observacion": "Evolución favorable."})
        self.assertIn("Nota clínica agregada", self.html(r))

    def test_cita_fuera_de_bloque_no_se_puede_atender(self):
        fuera = self.nueva_cita(HOY, "12:30")                 # entre 12:00 y 14:00
        cruza = self.nueva_cita(HOY, "11:45", pac=self.pac2)    # empieza dentro pero termina 12:15 > 12:00
        self.como("medico@citas.com", "medico123")
        agenda = self.html(self.c.get("/profesional/"))
        self.assertIn("Franjas de atención", agenda)
        self.assertIn("08:00 – 12:00", agenda)
        self.assertEqual(agenda.count("Fuera de franja"), 2)
        self.assertIn("fuera de la franja de atención", agenda)        # tooltip del botón deshabilitado
        for cid in (fuera, cruza):
            self.assertIn("fuera de la franja", self.marcar(cid, "Atendida"))
            self.assertEqual(self.cita(cid)["estado"], "Pendiente")
        r = self.post(f"/profesional/pacientes/{self.pac}/historial/agregar", {"cita_id": fuera, "observacion": "No debería guardarse."})
        self.assertIn("No se puede registrar la nota", self.html(r))
        self.assertFalse(self.q("SELECT id FROM historial_citas WHERE cita_id=?", (fuera,)))

    def test_atender_un_dia_distinto_al_de_la_cita_es_rechazado(self):
        manana = self.nueva_cita(MANANA, "09:00")
        ayer = self.nueva_cita("2030-01-04", "09:00", pac=self.pac2)    # viernes anterior
        self.como("medico@citas.com", "medico123")
        for cid in (manana, ayer):
            self.assertIn("Solo se puede atender el día de la cita", self.marcar(cid, "Atendida"))
            self.assertEqual(self.cita(cid)["estado"], "Pendiente")

    def test_inasistida_antes_de_la_tolerancia_es_rechazada(self):
        cid = self.nueva_cita(HOY, "09:00")
        self.como("medico@citas.com", "medico123")
        with self.reloj(HOY, "09:14"):
            self.assertIn("Podrá marcar Inasistida desde las 09:15", self.marcar(cid, "Inasistida"))
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")
        with self.reloj(HOY, "09:15"):
            self.assertIn("marcada como &#39;Inasistida&#39;", self.marcar(cid, "Inasistida"))

    def test_solo_el_profesional_asignado(self):
        cid = self.nueva_cita(HOY, "09:00", prof=self.sofia)
        self.como("medico@citas.com", "medico123")
        self.assertEqual(self.post(f"/profesional/citas/{cid}/estado", {"estado": "Atendida"}).status_code, 403)

    def test_override_de_administrador_queda_en_auditoria(self):
        cid = self.nueva_cita(MANANA, "09:00")                    # no es hoy: la regla lo impide
        self.como("recepcion@citas.com", "recep123")
        self.assertEqual(self.c.get(f"/admin/citas/{cid}/atencion").status_code, 403)   # recepción no atiende
        self.como("admin@citas.com", "admin123")
        self.assertIn("Solo se puede atender el día de la cita", self.html(self.c.get(f"/admin/citas/{cid}/atencion")))
        r = self.post(f"/admin/citas/{cid}/atencion", {"estado": "Atendida", "motivo": ""})
        self.assertIn("motivo del override es obligatorio", self.html(r))
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")
        r = self.post(f"/admin/citas/{cid}/atencion", {"estado": "Atendida", "motivo": "Atención adelantada por urgencia"})
        self.assertIn("override de administrador", self.html(r))
        self.assertEqual(self.cita(cid)["estado"], "Atendida")
        aud = self.q("SELECT * FROM auditoria WHERE accion='forzar_atencion' AND entidad_id=?", (cid,))
        self.assertEqual(len(aud), 1)
        self.assertEqual(aud[0]["override"], 1)
        self.assertEqual(aud[0]["usuario_id"], self.uid("admin@citas.com"))
        self.assertIn("urgencia", aud[0]["detalle"])

    def test_recepcion_solo_cancela(self):
        cid = self.nueva_cita(HOY, "09:00")
        self.como("recepcion@citas.com", "recep123")
        for estado in ("Atendida", "Inasistida", "Pendiente"):
            self.assertIn("Recepción solo puede cancelar", self.html(self.post(f"/recepcion/citas/{cid}/estado", {"estado": estado})))
        self.assertIn("actualizado a &#39;Cancelada&#39;", self.html(self.post(f"/recepcion/citas/{cid}/estado", {"estado": "Cancelada"})))


class TestExcepciones(AgendaBase):
    def test_bloqueo_de_dia_completo_impide_agendar_y_atender(self):
        cid = self.nueva_cita(MIERCOLES, "10:00")
        self.como("admin@citas.com", "admin123")
        datos = {"fecha": MIERCOLES, "tipo": "bloqueo", "dia_completo": "1", "motivo": "Congreso médico"}
        r = self.post(f"/admin/profesionales/{self.med}/excepciones", datos)
        self.assertEqual(r.status_code, 409)
        self.assertIn("no se ha guardado", self.html(r))
        self.assertFalse(self.q("SELECT id FROM excepciones_horario"))
        r = self.post(f"/admin/profesionales/{self.med}/excepciones", {**datos, "confirmar": "1"})
        self.assertIn("Bloqueo registrado", self.html(r))
        self.assertEqual(self.cita(cid)["requiere_reprogramacion"], 1)
        # agendar: rechazado y sin horas disponibles
        self.como("recepcion@citas.com", "recep123")
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.pac2, "profesional_id": self.med, "fecha": MIERCOLES, "hora": "09:00"})
        self.assertIn("no atiende", self.html(r))
        d = self.c.get(f"/api/disponibilidad?profesional_id={self.med}&fecha={MIERCOLES}").get_json()
        self.assertEqual(d["slots"], [])
        self.assertIn("bloqueada", d["mensaje"])
        # atender: rechazado ese día
        self.como("medico@citas.com", "medico123")
        with self.reloj(MIERCOLES, "10:05"):
            self.assertIn("No se puede marcar", self.marcar(cid, "Atendida"))
            self.assertIn("No atiende hoy", self.html(self.c.get("/profesional/")))
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")

    def test_bloqueo_parcial_resta_horas(self):
        self.como("admin@citas.com", "admin123")
        self.post(f"/admin/profesionales/{self.med}/excepciones",
                  {"fecha": MIERCOLES, "tipo": "bloqueo", "hora_inicio": "09:00", "hora_fin": "10:00", "motivo": "Reunión"})
        slots = self.c.get(f"/api/disponibilidad?profesional_id={self.med}&fecha={MIERCOLES}").get_json()["slots"]
        self.assertIn("08:30", slots); self.assertNotIn("09:00", slots); self.assertNotIn("09:30", slots); self.assertIn("10:00", slots)

    def test_turno_extra_permite_agendar(self):
        self.como("recepcion@citas.com", "recep123")
        self.assertEqual(self.c.get(f"/api/disponibilidad?profesional_id={self.med}&fecha={SABADO}").get_json()["slots"], [])
        self.como("admin@citas.com", "admin123")
        r = self.post(f"/admin/profesionales/{self.med}/excepciones",
                      {"fecha": SABADO, "tipo": "extra", "hora_inicio": "09:00", "hora_fin": "11:00", "motivo": "Jornada de salud"})
        self.assertIn("Turno extra registrado", self.html(r))
        self.como("recepcion@citas.com", "recep123")
        d = self.c.get(f"/api/disponibilidad?profesional_id={self.med}&fecha={SABADO}").get_json()
        self.assertEqual(d["slots"], ["09:00", "09:30", "10:00", "10:30"])
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.pac2, "profesional_id": self.med, "fecha": SABADO,
                                                 "hora": "09:30", "motivo": "Jornada"})
        self.assertIn("sin cruces de horario", self.html(r))
        cid = self.q("SELECT id FROM citas WHERE fecha=? AND hora='09:30:00'", (SABADO,))[0]["id"]
        self.como("medico@citas.com", "medico123")
        with self.reloj(SABADO, "09:35"):
            self.assertIn("marcada como &#39;Atendida&#39;", self.marcar(cid, "Atendida"))

    def test_excepciones_solapadas_y_medianoche(self):
        self.como("admin@citas.com", "admin123")
        base = {"fecha": SABADO, "tipo": "extra", "motivo": "Extra"}
        self.post(f"/admin/profesionales/{self.med}/excepciones", {**base, "hora_inicio": "09:00", "hora_fin": "11:00"})
        r = self.post(f"/admin/profesionales/{self.med}/excepciones", {**base, "hora_inicio": "10:00", "hora_fin": "12:00"})
        self.assertIn("se cruza", self.html(r))
        r = self.post(f"/admin/profesionales/{self.med}/excepciones", {**base, "hora_inicio": "22:00", "hora_fin": "01:00"})
        self.assertIn("medianoche", self.html(r))
        self.assertEqual(len(self.q("SELECT id FROM excepciones_horario")), 1)


class TestCambiosDeHorario(AgendaBase):
    def _bloque_lunes_manana(self):
        return self.q("SELECT * FROM horarios WHERE profesional_id=? AND dia_semana=0 AND hora_inicio='08:00:00'", (self.med,))[0]

    def test_cambio_de_horario_con_citas_afectadas_exige_confirmacion(self):
        cid = self.nueva_cita(LUNES_SIG, "09:00")
        h = self._bloque_lunes_manana()
        self.como("admin@citas.com", "admin123")
        nuevo = {"dia_semana": 0, "hora_inicio": "10:00", "hora_fin": "12:00"}
        r = self.post(f"/admin/profesionales/{self.med}/horarios/{h['id']}/editar", nuevo)
        self.assertEqual(r.status_code, 409)
        self.assertIn("1 cita(s) pendiente(s)", self.html(r))
        self.assertEqual(self._bloque_lunes_manana(), h)                              # nada cambió
        self.assertEqual(self.cita(cid)["requiere_reprogramacion"], 0)
        r = self.post(f"/admin/profesionales/{self.med}/horarios/{h['id']}/editar", {**nuevo, "confirmar": "1"})
        self.assertIn("Bloque actualizado", self.html(r))
        self.assertIn("marcadas como &#39;requiere reprogramación&#39;", self.html(r))
        viejo = self.q("SELECT * FROM horarios WHERE id=?", (h["id"],))[0]
        self.assertEqual((viejo["hora_inicio"], viejo["vigente_hasta"]), ("08:00:00", "2030-01-06"))  # cerrado, no editado
        self.assertTrue(self.q("SELECT id FROM horarios WHERE profesional_id=? AND dia_semana=0 AND hora_inicio='10:00:00' "
                               "AND vigente_desde=?", (self.med, HOY)))
        self.assertEqual(self.cita(cid)["requiere_reprogramacion"], 1)
        self.assertTrue(self.q("SELECT id FROM auditoria WHERE accion='marcar_reprogramacion' AND entidad_id=?", (cid,)))
        self.assertTrue(self.q("SELECT id FROM auditoria WHERE accion='editar' AND entidad='horario'"))
        # recepción la ve para reagendar; el profesional no puede atenderla
        self.como("recepcion@citas.com", "recep123")
        self.assertIn("Requiere reprogramación", self.html(self.c.get("/recepcion/citas?reprogramar=1&partial=1")))
        self.assertIn("Citas por reprogramar", self.html(self.c.get("/recepcion/")))
        r = self.post(f"/recepcion/citas/{cid}/editar", {"paciente_id": self.pac, "profesional_id": self.med,
                                                         "fecha": LUNES_SIG, "hora": "10:30", "motivo": "Reagendada"})
        self.assertIn("Cita actualizada", self.html(r))
        self.assertEqual(self.cita(cid)["requiere_reprogramacion"], 0)

    def test_cita_marcada_no_se_atiende(self):
        cid = self.nueva_cita(HOY, "09:00")
        con = sqlite3.connect(self.path)
        con.execute("UPDATE citas SET requiere_reprogramacion=1 WHERE id=?", (cid,)); con.commit(); con.close()
        self.como("medico@citas.com", "medico123")
        self.assertIn("requiere reprogramación", self.marcar(cid, "Atendida"))

    def test_cambio_de_vigencia_no_altera_citas_pasadas(self):
        pasada = self.nueva_cita("2030-01-02", "09:00", estado="Atendida")              # miércoles anterior
        pasada_pend = self.nueva_cita("2030-01-03", "09:00", pac=self.pac2)             # jueves anterior, sin cerrar
        h = self.q("SELECT * FROM horarios WHERE profesional_id=? AND dia_semana=2 AND hora_inicio='08:00:00'", (self.med,))[0]
        self.como("admin@citas.com", "admin123")
        r = self.post(f"/admin/profesionales/{self.med}/horarios/{h['id']}/editar",
                      {"dia_semana": 2, "hora_inicio": "10:00", "hora_fin": "12:00"})
        self.assertIn("Bloque actualizado", self.html(r))                              # sin citas futuras afectadas
        from app.services import agenda
        with self.app.test_request_context():
            self.assertEqual(agenda.franjas(self.med, date(2030, 1, 2))[0], ("08:00", "12:00"))   # el pasado conserva su horario
            self.assertEqual(agenda.franjas(self.med, date(2030, 1, 9))[0], ("10:00", "12:00"))   # el futuro usa el nuevo
        self.assertEqual(self.cita(pasada)["requiere_reprogramacion"], 0)
        self.assertEqual(self.cita(pasada)["estado"], "Atendida")
        self.assertEqual(self.cita(pasada_pend)["requiere_reprogramacion"], 0)

    def test_vigencia_futura_y_eliminar_es_cerrar(self):
        self.como("admin@citas.com", "admin123")
        r = self.post(f"/admin/profesionales/{self.med}/horarios",
                      {"dia_semana": 5, "hora_inicio": "08:00", "hora_fin": "10:00", "vigente_desde": "2030-02-01"})
        self.assertIn("Bloque de atención agregado", self.html(r))
        from app.services import agenda
        with self.app.test_request_context():
            self.assertEqual(agenda.franjas(self.med, date(2030, 1, 12)), [])                     # aún no rige
            self.assertEqual(agenda.franjas(self.med, date(2030, 2, 2)), [("08:00", "10:00")])
        r = self.post(f"/admin/profesionales/{self.med}/horarios",
                      {"dia_semana": 5, "hora_inicio": "08:00", "hora_fin": "10:00", "vigente_desde": "2029-12-01"})
        self.assertIn("no puede empezar en el pasado", self.html(r))
        h = self._bloque_lunes_manana()
        self.post(f"/admin/profesionales/{self.med}/horarios/{h['id']}/eliminar")
        self.assertEqual(self.q("SELECT vigente_hasta FROM horarios WHERE id=?", (h["id"],))[0]["vigente_hasta"], "2030-01-06")
        with self.app.test_request_context():
            self.assertEqual(agenda.franjas(self.med, date(2030, 1, 7)), [("14:00", "17:00")])

    def test_solapes_y_medianoche_en_horario_semanal(self):
        self.como("admin@citas.com", "admin123")
        r = self.post(f"/admin/profesionales/{self.med}/horarios", {"dia_semana": 0, "hora_inicio": "11:00", "hora_fin": "13:00"})
        self.assertIn("se cruza", self.html(r))
        r = self.post(f"/admin/profesionales/{self.med}/horarios", {"dia_semana": 5, "hora_inicio": "22:00", "hora_fin": "02:00"})
        self.assertIn("medianoche", self.html(r))
        # solape con un bloque de vigencia futura también se detecta
        self.post(f"/admin/profesionales/{self.med}/horarios", {"dia_semana": 5, "hora_inicio": "08:00", "hora_fin": "10:00",
                                                                "vigente_desde": "2030-03-01"})
        r = self.post(f"/admin/profesionales/{self.med}/horarios", {"dia_semana": 5, "hora_inicio": "09:00", "hora_fin": "11:00"})
        self.assertIn("se cruza", self.html(r))

    def test_solapes_concurrentes_solo_uno_gana(self):
        from app.models import horario
        from app.services import agenda
        resultados, barrera = [], threading.Barrier(2)

        def agregar(ini, fin):
            with self.app.test_request_context():
                barrera.wait()

                def cambio():
                    if horario.solapa(self.med, 5, ini, fin, HOY):
                        raise agenda.Rechazo("se cruza")
                    horario.agregar(self.med, 5, ini, fin, HOY)
                resultados.append(agenda.aplicar_cambio(self.med, cambio)[0])
        hilos = [threading.Thread(target=agregar, args=a) for a in (("08:00:00", "10:00:00"), ("09:00:00", "11:00:00"))]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(sorted(resultados), ["error", "ok"])
        self.assertEqual(len(self.q("SELECT id FROM horarios WHERE profesional_id=? AND dia_semana=5", (self.med,))), 1)

    def test_desactivar_profesional_marca_citas_futuras(self):
        futura = self.nueva_cita(LUNES_SIG, "09:00")
        pasada = self.nueva_cita("2030-01-03", "09:00", pac=self.pac2)
        self.como("admin@citas.com", "admin123")
        r = self.post(f"/admin/usuarios/{self.med}/estado")
        self.assertIn("quedaron marcadas para reprogramación", self.html(r))
        self.assertEqual(self.cita(futura)["requiere_reprogramacion"], 1)
        self.assertEqual(self.cita(pasada)["requiere_reprogramacion"], 0)


class TestProfesionalSinHorario(AgendaBase):
    def test_sin_horario_no_puede_agendar_ni_atender(self):
        self.como("admin@citas.com", "admin123")
        esp = self.q("SELECT id FROM especialidades LIMIT 1")[0]["id"]
        self.post("/admin/usuarios/nuevo", {"rol": "profesional", "nombre": "Dra. Sin Horario", "documento": "800800800",
                                            "telefono": "3110000000", "correo": "sinhorario@citas.com", "password": "medico123",
                                            "password2": "medico123", "especialidad_id": esp})
        prof = self.uid("sinhorario@citas.com")
        self.como("recepcion@citas.com", "recep123")
        r = self.post("/recepcion/citas/nueva", {"paciente_id": self.pac2, "profesional_id": prof, "fecha": MANANA, "hora": "09:00"})
        self.assertIn("no atiende", self.html(r))
        self.assertEqual(self.c.get(f"/api/disponibilidad?profesional_id={prof}&fecha={MANANA}").get_json()["slots"], [])
        cid = self.nueva_cita(HOY, "09:00", prof=prof)                 # p. ej. dato heredado
        self.como("sinhorario@citas.com", "medico123")
        agenda = self.html(self.c.get("/profesional/"))
        self.assertIn("No atiende hoy", agenda)
        self.assertNotIn('name="estado" value="Atendida"', agenda)      # ningún botón accionable
        # Sin bloques ese día el motivo es explícito (antes: "fuera de la franja")
        self.assertIn("Hoy no tiene horario de atención", self.marcar(cid, "Atendida"))
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")


class TestTurnoEnTiempoReal(AgendaBase):
    """El profesional solo registra atenciones y notas mientras la hora ACTUAL está dentro de un turno de hoy.
    Horario demo del lunes: 08:00-12:00 y 14:00-17:00. La salida es exclusiva."""
    FRANJAS = "Hoy atiende: 08:00–12:00 y 14:00–17:00."

    def test_no_atiende_antes_de_la_entrada(self):
        cid = self.nueva_cita(HOY, "08:00")
        self.como("medico@citas.com", "medico123")
        with self.reloj(HOY, "07:50"):
            html = self.marcar(cid, "Atendida")
        self.assertIn("Fuera de su horario de atención (ahora son las 07:50; su turno empieza a las 08:00)", html)
        self.assertIn(self.FRANJAS, html)
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")

    def test_no_atiende_en_la_pausa(self):
        cid = self.nueva_cita(HOY, "11:00")
        self.como("medico@citas.com", "medico123")
        with self.reloj(HOY, "13:00"):
            html = self.marcar(cid, "Atendida")
            self.assertIn("ahora son las 13:00; está en pausa; retoma a las 14:00", html)
            self.assertIn(self.FRANJAS, html)
            agenda = self.html(self.c.get("/profesional/"))
            self.assertIn("Fuera de su horario ahora", agenda)
            self.assertNotIn('name="estado" value="Atendida"', agenda)     # botones deshabilitados
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")

    def test_salida_exclusiva(self):
        cid = self.nueva_cita(HOY, "11:30")
        otra = self.nueva_cita(HOY, "11:00", pac=self.pac2)
        self.como("medico@citas.com", "medico123")
        with self.reloj(HOY, "11:59"):
            agenda = self.html(self.c.get("/profesional/"))
            self.assertIn("Turno activo:", agenda)
            self.assertIn("entrada 08:00 · salida 12:00", agenda)
            self.assertIn("marcada como &#39;Atendida&#39;", self.marcar(cid, "Atendida"))
        with self.reloj(HOY, "12:00"):
            self.assertIn("Fuera de su horario de atención (ahora son las 12:00", self.marcar(otra, "Atendida"))
        self.assertEqual(self.cita(otra)["estado"], "Pendiente")

    def test_cita_de_la_manana_despues_de_la_salida(self):
        cid = self.nueva_cita(HOY, "09:00")
        self.como("medico@citas.com", "medico123")
        with self.reloj(HOY, "17:20"):
            for estado in ("Atendida", "Inasistida"):
                html = self.marcar(cid, estado)
                self.assertIn("ahora son las 17:20; su turno de hoy terminó a las 17:00", html)
                self.assertIn(self.FRANJAS, html)
        self.assertEqual(self.cita(cid)["estado"], "Pendiente")

    def test_notas_clinicas_solo_dentro_del_turno(self):
        cid = self.nueva_cita(HOY, "09:00")
        self.como("medico@citas.com", "medico123")
        url = f"/profesional/pacientes/{self.pac}/historial/agregar"
        self.assertIn("Nota clínica agregada", self.html(self.post(url, {"cita_id": cid, "observacion": "Nota dentro del turno."})))
        nid = self.q("SELECT id FROM historial_citas WHERE cita_id=?", (cid,))[0]["id"]
        with self.reloj(HOY, "12:30"):
            html = self.html(self.post(url, {"cita_id": cid, "observacion": "Nota en la pausa."}))
            self.assertIn("No se puede registrar la nota: Fuera de su horario de atención (ahora son las 12:30", html)
            html = self.html(self.post(f"/profesional/historial/{nid}/editar", {"observacion": "Corrección en la pausa."}))
            self.assertIn("No se puede corregir la nota: Fuera de su horario de atención", html)
            vista = self.html(self.c.get(f"/profesional/pacientes/{self.pac}/historial"))
            self.assertIn("está en pausa; retoma a las 14:00", vista)                  # aviso y tooltip con el motivo real
            self.assertNotIn(f'action="/profesional/pacientes/{self.pac}/historial/agregar"', vista)
        self.assertEqual(len(self.q("SELECT id FROM historial_citas WHERE cita_id=?", (cid,))), 1)
        with self.reloj(HOY, "14:00"):                                                  # vuelve a abrir en el turno de la tarde
            html = self.html(self.post(f"/profesional/historial/{nid}/editar", {"observacion": "Corrección en la tarde."}))
            self.assertIn("Nota actualizada", html)

    def test_turno_extra_fuera_del_horario_habitual(self):
        self.como("admin@citas.com", "admin123")
        self.post(f"/admin/profesionales/{self.med}/excepciones",
                  {"fecha": SABADO, "tipo": "extra", "hora_inicio": "09:00", "hora_fin": "11:00", "motivo": "Jornada de salud"})
        cid = self.nueva_cita(SABADO, "09:00")
        self.como("medico@citas.com", "medico123")
        with self.reloj(SABADO, "11:05"):
            html = self.marcar(cid, "Atendida")
            self.assertIn("su turno de hoy terminó a las 11:00). Hoy atiende: 09:00–11:00.", html)
        with self.reloj(SABADO, "10:00"):
            self.assertIn("marcada como &#39;Atendida&#39;", self.marcar(cid, "Atendida"))

    def test_bloqueo_de_dia_completo_explica_el_motivo(self):
        cid = self.nueva_cita(MIERCOLES, "10:00")
        self.como("admin@citas.com", "admin123")
        self.post(f"/admin/profesionales/{self.med}/excepciones",
                  {"fecha": MIERCOLES, "tipo": "bloqueo", "dia_completo": "1", "motivo": "Congreso", "confirmar": "1"})
        self.como("medico@citas.com", "medico123")
        with self.reloj(MIERCOLES, "10:05"):
            self.assertIn("Hoy no tiene horario de atención", self.marcar(cid, "Atendida"))

    def test_recepcion_y_admin_no_estan_limitados_por_turno(self):
        cancelar = self.nueva_cita(HOY, "09:00")
        forzar = self.nueva_cita(HOY, "10:00", pac=self.pac2)
        with self.reloj(HOY, "20:00"):
            self.como("recepcion@citas.com", "recep123")
            self.assertIn("actualizado a &#39;Cancelada&#39;",
                          self.html(self.post(f"/recepcion/citas/{cancelar}/estado", {"estado": "Cancelada"})))
            self.como("admin@citas.com", "admin123")
            self.assertIn("Fuera de su horario de atención", self.html(self.c.get(f"/admin/citas/{forzar}/atencion")))
            r = self.post(f"/admin/citas/{forzar}/atencion", {"estado": "Atendida", "motivo": "Registro tardío autorizado"})
            self.assertIn("override de administrador", self.html(r))
        self.assertEqual(self.cita(cancelar)["estado"], "Cancelada")
        self.assertEqual(self.cita(forzar)["estado"], "Atendida")

    def test_turno_en_y_zona_horaria_configurable(self):
        from app.services import agenda
        with self.app.test_request_context():
            self.assertEqual(agenda.turno_en(self.med, datetime(2030, 1, 7, 8, 0)), ("08:00", "12:00"))   # entrada inclusiva
            self.assertIsNone(agenda.turno_en(self.med, datetime(2030, 1, 7, 12, 0)))                      # salida exclusiva
            self.assertIsNone(agenda.turno_en(self.med, datetime(2030, 1, 12, 9, 0)))                      # sábado sin horario
            # 09:10 en Bogotá = 14:10 UTC: con TZ=UTC el "ahora" del negocio cae en el turno de la tarde
            self.app.config["TZ"] = "UTC"
            self.assertEqual(agenda.turno_en(self.med), ("14:00", "17:00"))


class TestZonaHoraria(unittest.TestCase):
    def test_hoy_calculado_en_america_bogota(self):
        from app import create_app
        from test_app import TestConfig
        app = create_app(TestConfig)
        from app import utils
        # 2026-03-10 03:00 UTC = 2026-03-09 22:00 en Bogotá (UTC-5)
        instante = datetime(2026, 3, 10, 3, 0, tzinfo=timezone.utc)
        with app.app_context(), mock.patch("app.utils._utcnow", return_value=instante):
            self.assertEqual(utils.hoy(), date(2026, 3, 9))
            self.assertEqual(utils.ahora(), datetime(2026, 3, 9, 22, 0))
            app.config["TZ"] = "UTC"                                   # configurable con TZ
            self.assertEqual(utils.hoy(), date(2026, 3, 10))


if __name__ == "__main__":
    unittest.main()
