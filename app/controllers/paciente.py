from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask import current_app
from werkzeug.security import check_password_hash

from ..models import auditoria, cita, notificacion, recordatorio, usuario
from ..utils import ahora, clean, role_required
from ..validators import validar_persona
from .correos import avisar

bp = Blueprint("paciente", __name__, url_prefix="/paciente")
pac = role_required("paciente")


def _con_anticipacion(c):
    """True si faltan al menos ANTICIPACION_HORAS para la cita (hora del negocio)."""
    momento = datetime.strptime(f"{c['fecha']} {c['hora']}", "%Y-%m-%d %H:%M")
    return momento - ahora() >= timedelta(hours=current_app.config["ANTICIPACION_HORAS"])


def _cita_propia(cid):
    c = cita.get(cid)
    if not c or c["paciente_id"] != session["user_id"]:
        abort(404)
    return c


@bp.route("/")
@pac
def dashboard():
    uid = session["user_id"]
    citas = cita.proximas_del_paciente(uid)
    return render_template(
        "paciente/dashboard.html", citas=citas,
        profesionales=usuario.listar("profesional", solo_activos=True),
        notificaciones=recordatorio.por_paciente(uid),
        pendientes=sum(1 for c in citas if c["estado"] == "Pendiente"),
        horas=current_app.config["ANTICIPACION_HORAS"],
    )


# HU-03
@bp.route("/citas/solicitar", methods=["POST"])
@pac
def solicitar():
    f = request.form
    motivo = clean(f.get("motivo"))
    cid, error = None, None
    if not (3 <= len(motivo) <= 255):
        error = "Describa el motivo de la consulta (3 a 255 caracteres)."
    else:
        cid, error = cita.programar(session["user_id"], f.get("profesional_id"), f.get("fecha"), f.get("hora"),
                                    motivo)
    if error:
        flash(error, "danger")
    else:
        auditoria.registrar("crear", "cita", cid, {"origen": "paciente"})
        notificacion.por_cita(cita.get(cid), "creada")
        flash("¡Cita solicitada exitosamente en línea! (HU-03)", "success")
        r = recordatorio.enviar_para_cita(cid, "confirmacion")
        if r["modo"] in ("smtp", "pendiente"):
            flash("Le enviamos una confirmación a su correo.", "info")
    return redirect(url_for("paciente.dashboard"))


# HU-04
@bp.route("/citas/<int:cid>/reprogramar", methods=["POST"])
@pac
def reprogramar(cid):
    c = _cita_propia(cid)
    f = request.form
    if c["estado"] != "Pendiente":
        flash("Solo se pueden reprogramar citas pendientes.", "warning")
    elif not _con_anticipacion(c):
        flash(f"Solo puede reprogramar con al menos {current_app.config['ANTICIPACION_HORAS']} horas "
              "de anticipación. Comuníquese con recepción.", "warning")
    else:
        _, error = cita.programar(session["user_id"], c["profesional_id"], f.get("nueva_fecha"),
                                  f.get("nueva_hora"), cita_id=cid)
        if error:
            flash(error, "danger")
        else:
            auditoria.registrar("reprogramar", "cita", cid, {"antes": f"{c['fecha']} {c['hora']}",
                                                              "despues": f"{f.get('nueva_fecha')} {f.get('nueva_hora')}",
                                                              "origen": "paciente"})
            flash("Cita reprogramada exitosamente (HU-04).", "success")
            notificacion.por_cita(cita.get(cid), "reprogramada")
            recordatorio.enviar_para_cita(cid, "confirmacion")
    return redirect(url_for("paciente.dashboard"))


@bp.route("/citas/<int:cid>/cancelar", methods=["POST"])
@pac
def cancelar(cid):
    c = _cita_propia(cid)
    if c["estado"] != "Pendiente":
        flash("Solo se pueden cancelar citas pendientes.", "warning")
    elif not _con_anticipacion(c):
        flash(f"Solo puede cancelar con al menos {current_app.config['ANTICIPACION_HORAS']} horas "
              "de anticipación. Comuníquese con recepción.", "warning")
    else:
        cita.cambiar_estado(cid, "Cancelada")
        auditoria.registrar("cambiar_estado", "cita", cid, {"de": c["estado"], "a": "Cancelada", "origen": "paciente"})
        flash("Su cita fue cancelada (HU-04).", "success")
        notificacion.por_cita(c, "cancelada")
    return redirect(url_for("paciente.dashboard"))


@bp.route("/recordatorio/<int:cid>", methods=["POST"])
@pac
def recordatorio_cita(cid):
    c = _cita_propia(cid)
    avisar(recordatorio.enviar_para_cita(c["id"], "recordatorio"))
    return redirect(url_for("paciente.dashboard"))


# Perfil (actualizar datos propios)
@bp.route("/perfil", methods=["GET", "POST"])
@pac
def perfil():
    """Compatibilidad: el perfil ahora vive en «Mi cuenta» (común a todos los roles)."""
    u = usuario.get(session["user_id"])
    if request.method == "GET":
        return redirect(url_for("cuenta.ver"))
    if request.method == "POST":
        form = request.form.to_dict()
        form["documento"] = u["documento"]          # el documento no se modifica
        datos, errores = validar_persona(form, "paciente", password_obligatoria=False, telefono_obligatorio=True)
        if not errores and datos["password"]:
            if not check_password_hash(u["password_hash"], form.get("password_actual", "")):
                errores.append("La contraseña actual no es correcta.")
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"], excluir_id=u["id"])
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            usuario.actualizar(u["id"], datos)
            auditoria.registrar("editar", "usuario", u["id"],
                                {"origen": "perfil", "password_cambiada": bool(datos["password"])})
            session["nombre"] = datos["nombre"]
            flash("Sus datos fueron actualizados.", "success")
            return redirect(url_for("cuenta.ver"))
    return render_template("paciente/perfil.html", u=u, f=request.form or u)


@bp.route("/citas/<int:cid>/calendario.ics")
@pac
def calendario(cid):
    """Descarga la cita como evento de calendario (Google Calendar, Outlook, celular)."""
    c = _cita_propia(cid)
    inicio = datetime.strptime(f"{c['fecha']} {c['hora']}", "%Y-%m-%d %H:%M")
    fin = inicio + timedelta(minutes=current_app.config.get("SLOT_MINUTES", 30))
    fmt = "%Y%m%dT%H%M%S"
    tz = current_app.config.get("TZ", "America/Bogota")
    def texto(s):
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")

    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UCC//CitasMedicas//ES", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT", f"UID:cita-{c['id']}@citasmedicas-ucc", f"DTSTAMP:{ahora().strftime(fmt)}",
        f"DTSTART;TZID={tz}:{inicio.strftime(fmt)}", f"DTEND;TZID={tz}:{fin.strftime(fmt)}",
        f"SUMMARY:{texto('Cita médica con ' + c['profesional_nombre'])}",
        f"DESCRIPTION:{texto((c['especialidad'] or 'Consulta') + ' - Estado: ' + c['estado'])}",
        "BEGIN:VALARM", "TRIGGER:-PT1H", "ACTION:DISPLAY", "DESCRIPTION:Recordatorio de cita", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
    return ics, 200, {"Content-Type": "text/calendar; charset=utf-8",
                      "Content-Disposition": f"attachment; filename=cita_{c['id']}.ics"}
