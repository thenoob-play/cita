"""Recordatorios y confirmaciones por correo, con envío en segundo plano.

Flujo: cada correo se registra primero en `recordatorios` con modo='pendiente' (rápido, dentro de
la petición) y luego un hilo con app_context lo procesa:
* MAIL_SERVER configurado -> envío REAL por SMTP (modo 'smtp' o 'error').
* Sin MAIL_SERVER -> modo demostración ('demo'): no sale, se puede ver en la vista previa.
Con MAIL_ASYNC=0 (y siempre en pruebas) el procesamiento es síncrono.

Privacidad: el cuerpo NUNCA incluye el motivo de consulta; solo fecha, hora y profesional.
"""
import smtplib
import ssl
import threading
from datetime import timedelta
from email.message import EmailMessage

from flask import current_app

from ..db import get_db
from ..utils import ahora, fecha_es, hoy
from . import cita as cita_model

ASUNTOS = {"confirmacion": "Confirmación de cita médica", "recordatorio": "Recordatorio de cita médica"}


def smtp_configurado():
    return bool(current_app.config.get("MAIL_SERVER"))


def _texto(c, tipo):
    cab = ("Su cita médica ha sido registrada." if tipo == "confirmacion"
           else "Le recordamos su próxima cita médica.")
    return (
        f"Estimado(a) {c['paciente_nombre']},\n\n{cab}\n\n"
        f"  Fecha: {fecha_es(c['fecha'])}\n  Hora: {c['hora']}\n"
        f"  Profesional: {c['profesional_nombre']}\n\n"
        "Si no puede asistir, por favor reprograme o cancele su cita desde el portal.\n\n"
        "Sistema de Gestión de Citas Médicas - UCC"
    )


def enviar_smtp(destino, asunto, cuerpo):
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], destino, asunto
    msg.set_content(cuerpo)
    ctx = ssl.create_default_context()
    if cfg["MAIL_PORT"] == 465:
        server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], 465, timeout=20, context=ctx)
    else:
        server = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=20)
        if cfg["MAIL_USE_TLS"]:
            server.starttls(context=ctx)
    try:
        if cfg["MAIL_USER"]:
            server.login(cfg["MAIL_USER"], cfg["MAIL_PASSWORD"])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def en_segundo_plano(fn, *args, sincrono=None):
    """Ejecuta fn(*args) en un hilo con app_context (o en línea si MAIL_ASYNC=0 / sincrono=True)."""
    app = current_app._get_current_object()
    if sincrono is None:
        sincrono = not app.config.get("MAIL_ASYNC", True)
    if sincrono:
        return fn(*args)

    def worker():
        with app.app_context():
            try:
                fn(*args)
            except Exception as exc:  # el hilo no debe morir en silencio
                app.logger.warning("Tarea de correo en segundo plano: %s", exc)
    threading.Thread(target=worker, daemon=True, name="correo").start()
    return None


# ---------------- Cola ----------------
def _registrar(c, tipo):
    return get_db().execute(
        """INSERT INTO recordatorios (cita_id, correo_destino, asunto, mensaje, tipo, modo, enviado_en)
           VALUES (%s,%s,%s,%s,%s,'pendiente',%s)""",
        (c["id"], c["paciente_correo"], ASUNTOS.get(tipo, ASUNTOS["recordatorio"]), _texto(c, tipo), tipo,
         ahora().strftime("%Y-%m-%d %H:%M:%S")))


def _procesar(rid):
    r = get(rid)
    if not r or r["modo"] != "pendiente":
        return
    modo, cuerpo = "demo", r["mensaje"]
    if smtp_configurado():
        try:
            enviar_smtp(r["correo_destino"], r["asunto"], r["mensaje"])
            modo = "smtp"
        except Exception as exc:
            modo = "error"
            cuerpo += f"\n\n[ERROR SMTP: {exc}]"
            current_app.logger.warning("Fallo SMTP: %s", exc)
    get_db().execute("UPDATE recordatorios SET modo=%s, mensaje=%s, enviado_en=%s WHERE id=%s AND modo='pendiente'",
                     (modo, cuerpo, ahora().strftime("%Y-%m-%d %H:%M:%S"), rid))


def _procesar_lote(ids):
    for rid in ids:
        _procesar(rid)


def procesar_pendientes(sincrono=None):
    """Reintenta la cola (correos que quedaron 'pendiente', p. ej. si la app se reinició)."""
    ids = [r["id"] for r in get_db().all("SELECT id FROM recordatorios WHERE modo='pendiente' ORDER BY id")]
    if ids:
        en_segundo_plano(_procesar_lote, ids, sincrono=sincrono)
    return len(ids)


def enviar_para_cita(cita_id, tipo="recordatorio"):
    """Encola el correo de una cita y lo despacha. Devuelve dict {id, ok, modo, correo}.
    En modo asíncrono `modo` puede ser 'pendiente' (aún en cola)."""
    c = cita_model.get(cita_id)
    if not c:
        return {"id": None, "ok": False, "modo": "error", "correo": None}
    rid = _registrar(c, tipo)
    en_segundo_plano(_procesar, rid)
    r = get(rid)
    return {"id": rid, "ok": r["modo"] != "error", "modo": r["modo"], "correo": r["correo_destino"]}


def enviar_manana(sincrono=None):
    """Encola el recordatorio de todas las citas pendientes de mañana que aún no lo tienen
    (en cola o enviado) y lo despacha en segundo plano. Devuelve cuántos encoló."""
    manana = (hoy() + timedelta(days=1)).isoformat()
    citas = cita_model.buscar({"estado": "Pendiente", "desde": manana, "hasta": manana}, limite=100000)
    ids = []
    for c in citas:
        if c.get("requiere_reprogramacion"):
            continue        # no recordar una cita que hay que reagendar
        ya = get_db().one("SELECT COUNT(*) AS n FROM recordatorios WHERE cita_id=%s AND tipo='recordatorio' "
                          "AND modo <> 'error'", (c["id"],))["n"]
        if not ya:
            ids.append(_registrar(c, "recordatorio"))
    if ids:
        en_segundo_plano(_procesar_lote, ids, sincrono=sincrono)
    return len(ids)


def resumen(ids):
    if not ids:
        return {}
    marcas = ",".join(["%s"] * len(ids))
    rows = get_db().all(f"SELECT modo, COUNT(*) AS n FROM recordatorios WHERE id IN ({marcas}) GROUP BY modo", ids)
    return {r["modo"]: r["n"] for r in rows}


# ---------------- Consultas ----------------
def get(rid):
    return get_db().one(
        """SELECT r.*, c.paciente_id, c.fecha, c.hora FROM recordatorios r
           JOIN citas c ON c.id = r.cita_id WHERE r.id=%s""", (rid,))


def por_paciente(paciente_id, limite=10):
    return get_db().all(
        f"""SELECT r.id, r.asunto, r.tipo, r.modo, r.enviado_en, c.fecha, c.hora
            FROM recordatorios r JOIN citas c ON c.id = r.cita_id
            WHERE c.paciente_id = %s ORDER BY r.id DESC LIMIT {int(limite)}""", (paciente_id,))


def recientes(limite=8):
    return get_db().all(
        f"""SELECT r.id, r.correo_destino, r.asunto, r.tipo, r.modo, r.enviado_en
            FROM recordatorios r ORDER BY r.id DESC LIMIT {int(limite)}""")
