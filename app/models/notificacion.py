"""Centro de notificaciones internas (campana de la barra superior).

Son avisos dentro de la aplicación, independientes de los correos de `recordatorio`.
Crear una notificación NUNCA debe romper la operación principal: los errores se registran y se ignoran.
Privacidad: el texto no incluye el motivo de consulta ni contenido clínico.
"""
from flask import current_app, has_request_context, session, url_for

from ..db import get_db
from ..utils import ahora, fecha_es

TIPOS = {
    "info": ("fa-circle-info", "nt-info"),
    "exito": ("fa-circle-check", "nt-exito"),
    "alerta": ("fa-triangle-exclamation", "nt-alerta"),
    "peligro": ("fa-circle-xmark", "nt-peligro"),
    "cita": ("fa-calendar-check", "nt-cita"),
}


def crear(usuario_id, titulo, mensaje, url=None, tipo="info"):
    try:
        return get_db().execute(
            """INSERT INTO notificaciones (usuario_id, tipo, titulo, mensaje, url, leida, created_at)
               VALUES (%s,%s,%s,%s,%s,0,%s)""",
            (int(usuario_id), tipo if tipo in TIPOS else "info", titulo[:120], mensaje[:255],
             (url or None) and url[:255], ahora().strftime("%Y-%m-%d %H:%M:%S")))
    except Exception as exc:  # no interrumpir el flujo principal
        current_app.logger.warning("No se pudo crear la notificación: %s", exc)
        return None


def a_roles(roles, titulo, mensaje, url=None, tipo="info", excluir=None):
    """Notifica a todos los usuarios activos de los roles indicados."""
    try:
        marcas = ",".join(["%s"] * len(roles))
        ids = [r["id"] for r in get_db().all(
            f"SELECT id FROM usuarios WHERE activo = 1 AND rol IN ({marcas})", list(roles))]
    except Exception as exc:
        current_app.logger.warning("No se pudieron leer destinatarios: %s", exc)
        return 0
    n = 0
    for uid in ids:
        if uid != excluir and crear(uid, titulo, mensaje, url, tipo):
            n += 1
    return n


def _actor():
    return session.get("user_id") if has_request_context() else None


EVENTOS = {
    # evento: (tipo, título, plantilla para paciente, plantilla para profesional)
    "creada": ("cita", "Nueva cita programada",
               "Tiene una cita con {prof} el {fecha} a las {hora}.",
               "Nueva cita con {pac} el {fecha} a las {hora}."),
    "reprogramada": ("alerta", "Cita reprogramada",
                     "Su cita con {prof} quedó para el {fecha} a las {hora}.",
                     "La cita con {pac} se movió al {fecha} a las {hora}."),
    "cancelada": ("peligro", "Cita cancelada",
                  "Su cita con {prof} del {fecha} a las {hora} fue cancelada.",
                  "Se canceló la cita con {pac} del {fecha} a las {hora}."),
    "atendida": ("exito", "Cita atendida",
                 "Su cita con {prof} del {fecha} quedó registrada como atendida.", None),
    "inasistida": ("alerta", "Inasistencia registrada",
                   "No registramos su asistencia a la cita con {prof} del {fecha} a las {hora}.", None),
}


def por_cita(c, evento):
    """Avisa al paciente y al profesional de una cita (excepto a quien hizo el cambio)."""
    if not c or evento not in EVENTOS:
        return
    tipo, titulo, msg_pac, msg_prof = EVENTOS[evento]
    datos = {"prof": c["profesional_nombre"], "pac": c["paciente_nombre"],
             "fecha": fecha_es(c["fecha"]), "hora": c["hora"]}
    actor = _actor()
    if msg_pac and c["paciente_id"] != actor:
        crear(c["paciente_id"], titulo, msg_pac.format(**datos), url_for("paciente.dashboard"), tipo)
    if msg_prof and c["profesional_id"] != actor:
        crear(c["profesional_id"], titulo, msg_prof.format(**datos),
              url_for("profesional.agenda", fecha=c["fecha"]), tipo)


# ---------- Lectura ----------
def no_leidas(uid):
    return get_db().one("SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id=%s AND leida=0", (uid,))["n"]


def _decorar(rows):
    for r in rows:
        r["icono"], r["clase"] = TIPOS.get(r["tipo"], TIPOS["info"])
    return rows


def listar(uid, solo_no_leidas=False, limite=20, offset=0):
    sql = "SELECT * FROM notificaciones WHERE usuario_id=%s"
    if solo_no_leidas:
        sql += " AND leida=0"
    sql += f" ORDER BY id DESC LIMIT {int(limite)} OFFSET {int(offset)}"
    return _decorar(get_db().all(sql, (uid,)))


def contar(uid, solo_no_leidas=False):
    sql = "SELECT COUNT(*) AS n FROM notificaciones WHERE usuario_id=%s" + (" AND leida=0" if solo_no_leidas else "")
    return get_db().one(sql, (uid,))["n"]


def get(nid, uid):
    return get_db().one("SELECT * FROM notificaciones WHERE id=%s AND usuario_id=%s", (nid, uid))


# ---------- Escritura ----------
def marcar_leida(nid, uid):
    return get_db().rowcount("UPDATE notificaciones SET leida=1 WHERE id=%s AND usuario_id=%s", (nid, uid))


def marcar_todas(uid):
    return get_db().rowcount("UPDATE notificaciones SET leida=1 WHERE usuario_id=%s AND leida=0", (uid,))


def eliminar(nid, uid):
    return get_db().rowcount("DELETE FROM notificaciones WHERE id=%s AND usuario_id=%s", (nid, uid))


def limpiar_leidas(uid):
    return get_db().rowcount("DELETE FROM notificaciones WHERE usuario_id=%s AND leida=1", (uid,))
