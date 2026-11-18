from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..db import IntegrityError
from ..models import auditoria, cita, historial, horario, notificacion, usuario
from ..services import agenda as agenda_srv
from ..utils import ahora, clean, destino_seguro, hoy, parse_fecha, role_required

bp = Blueprint("profesional", __name__, url_prefix="/profesional")
medico = role_required("profesional")
ESTADOS_MEDICO = ("Pendiente", "Atendida", "Inasistida")


# ---------------- Agenda diaria (HU-06) ----------------
@bp.route("/")
@medico
def agenda():
    pid = session["user_id"]
    fecha = parse_fecha(request.args.get("fecha")) or hoy()
    q = clean(request.args.get("q")) or None
    pacientes = cita.pacientes_de_profesional(pid, q)
    if request.args.get("partial"):
        return render_template("profesional/_pacientes.html", pacientes=pacientes)
    citas = cita.buscar({"profesional_id": pid, "desde": fecha.isoformat(), "hasta": fecha.isoformat()},
                        limite=1000, asc=True)
    yo, momento = usuario.get(pid), ahora()
    bloques = agenda_srv.bloques_efectivos(pid, fecha)
    for c in citas:
        c["fuera_bloque"] = not agenda_srv.en_bloque(pid, fecha, c["hora"], bloques)
        c["acciones"] = agenda_srv.acciones_de_estado(c, yo, momento)
    es_hoy = fecha == momento.date()
    turno = agenda_srv.turno_en(pid, momento, bloques) if es_hoy else None
    return render_template(
        "profesional/agenda.html", citas=citas, pacientes=pacientes, fecha=fecha.isoformat(),
        anterior=(fecha - timedelta(days=1)).isoformat(), siguiente=(fecha + timedelta(days=1)).isoformat(),
        es_hoy=es_hoy, horarios=horario.listar(pid, hoy().isoformat()),
        franjas=[(agenda_srv.a_hora(a), agenda_srv.a_hora(b)) for a, b in bloques],
        turno=turno, hora_actual=momento.strftime("%H:%M"),
        motivo_turno=None if turno or not es_hoy else agenda_srv.motivo_fuera_de_turno(momento, bloques),
    )


@bp.route("/citas/<int:cid>/estado", methods=["POST"])
@medico
def cita_estado(cid):
    c = cita.get(cid)
    if not c or c["profesional_id"] != session["user_id"]:
        abort(403)
    estado = request.form.get("estado")
    if estado not in ESTADOS_MEDICO:
        abort(400, "Estado inválido.")
    ok, motivo = agenda_srv.puede_atender(c, usuario.get(session["user_id"]), ahora(), estado)
    if not ok:
        flash(f"No se puede marcar la cita como '{estado}': {motivo}", "warning")
    else:
        try:
            cita.cambiar_estado(cid, estado)
            auditoria.registrar("cambiar_estado", "cita", cid, {"de": c["estado"], "a": estado})
            if estado != c["estado"] and estado in ("Atendida", "Inasistida"):
                notificacion.por_cita(c, estado.lower())
            flash(f"Cita marcada como '{estado}'.", "success")
        except IntegrityError:
            flash("No se puede reactivar: ese horario ya está ocupado por otra cita.", "danger")
    return redirect(destino_seguro(request.form.get("next"), defecto=url_for("profesional.agenda")))


# ---------------- Historial clínico (HU-08) ----------------
def _paciente_o_403(paciente_id):
    p = usuario.get(paciente_id)
    if not p or p["rol"] != "paciente":
        abort(404)
    if not cita.profesional_atiende_a(session["user_id"], paciente_id):
        abort(403)
    return p


def _volver_historial(paciente_id):
    return redirect(url_for("profesional.historial_paciente", paciente_id=paciente_id))


@bp.route("/pacientes/<int:paciente_id>/historial")
@medico
def historial_paciente(paciente_id):
    p = _paciente_o_403(paciente_id)
    auditoria.registrar("leer_historial", "paciente", paciente_id)
    yo, momento = usuario.get(session["user_id"]), ahora()
    mis_citas = cita.buscar({"paciente_id": paciente_id, "profesional_id": session["user_id"]})
    regla = {c["id"]: agenda_srv.puede_atender(c, yo, momento) for c in mis_citas}
    atendibles = {cid for cid, (ok, _) in regla.items() if ok}
    notas = historial.por_paciente(paciente_id)
    for n in notas:
        ok, motivo = regla.get(n["cita_id"], (False, ""))
        n["corregible"], n["motivo_bloqueo"] = (True, "") if ok else (
            False, motivo or "Solo puede corregir notas de citas que está atendiendo hoy dentro de su franja.")
    bloques_hoy = agenda_srv.bloques_efectivos(session["user_id"], momento.date())
    turno = agenda_srv.turno_en(session["user_id"], momento, bloques_hoy)
    resp = render_template(
        "profesional/historial.html", paciente=p,
        citas=cita.buscar({"paciente_id": paciente_id}),
        mis_citas=[c for c in mis_citas if c["id"] in atendibles],
        notas=notas, turno=turno,
        motivo_turno=None if turno else agenda_srv.motivo_fuera_de_turno(momento, bloques_hoy),
    )
    return resp, 200, {"Cache-Control": "no-store"}


@bp.route("/pacientes/<int:paciente_id>/historial/agregar", methods=["POST"])
@medico
def historial_agregar(paciente_id):
    _paciente_o_403(paciente_id)
    obs = clean(request.form.get("observacion"))
    c = cita.get(int(request.form["cita_id"])) if request.form.get("cita_id", "").isdigit() else None
    if not c or c["profesional_id"] != session["user_id"] or c["paciente_id"] != paciente_id:
        flash("Seleccione una de sus citas con este paciente.", "danger")
    elif not (r := agenda_srv.puede_atender(c, usuario.get(session["user_id"]), ahora()))[0]:
        flash(f"No se puede registrar la nota: {r[1]}", "warning")
    elif len(obs) < 5:
        flash("La observación debe tener al menos 5 caracteres.", "danger")
    else:
        hid = historial.crear(c["id"], obs, session["user_id"])
        auditoria.registrar("crear_nota", "historial", hid, {"cita_id": c["id"], "paciente_id": paciente_id})
        flash("Nota clínica agregada al historial (HU-08).", "success")
    return _volver_historial(paciente_id)


def _nota_propia(hid):
    h = historial.get(hid) or abort(404)
    if h["registrado_por"] != session["user_id"]:
        abort(403)
    return h


@bp.route("/historial/<int:hid>/editar", methods=["POST"])
@medico
def historial_editar(hid):
    """Las notas son inmutables: 'editar' agrega una nota de corrección que referencia a la original."""
    h = _nota_propia(hid)
    c = cita.get(h["cita_id"])
    obs = clean(request.form.get("observacion"))
    permitido, motivo = agenda_srv.puede_atender(c, usuario.get(session["user_id"]), ahora())
    if h["anulada"]:
        flash("La nota está anulada: no se puede corregir.", "warning")
    elif not permitido:
        flash(f"No se puede corregir la nota: {motivo}", "warning")
    elif historial.fue_corregida(hid):
        flash("Esa nota ya tiene una corrección: corrija la versión vigente.", "warning")
    elif len(obs) < 5:
        flash("La observación debe tener al menos 5 caracteres.", "danger")
    else:
        nuevo = historial.crear(h["cita_id"], obs, session["user_id"], corrige_a=hid)
        auditoria.registrar("corregir_nota", "historial", nuevo, {"corrige_a": hid, "cita_id": h["cita_id"]})
        flash("Nota actualizada: se registró una corrección y la versión anterior se conserva.", "success")
    return _volver_historial(c["paciente_id"])


@bp.route("/historial/<int:hid>/eliminar", methods=["POST"])
@medico
def historial_eliminar(hid):
    """Las notas no se borran: se anulan con un motivo obligatorio."""
    h = _nota_propia(hid)
    c = cita.get(h["cita_id"])
    motivo = clean(request.form.get("motivo"))
    if len(motivo) < 5 or len(motivo) > 255:
        flash("Indique el motivo de la anulación (5 a 255 caracteres).", "danger")
    elif historial.anular(hid, motivo):
        auditoria.registrar("anular_nota", "historial", hid, {"motivo": motivo, "cita_id": h["cita_id"]})
        flash("Nota eliminada del historial vigente (quedó anulada con su motivo).", "success")
    else:
        flash("La nota ya estaba anulada.", "info")
    return _volver_historial(c["paciente_id"])
