import secrets
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..db import IntegrityError
from ..models import auditoria, cita, historial, notificacion, recordatorio, usuario
from ..utils import ESTADOS, clean, destino_seguro, hoy, pagina_actual, role_required
from ..validators import validar_persona
from .correos import avisar

bp = Blueprint("recepcion", __name__, url_prefix="/recepcion")
staff = role_required("recepcionista", "administrador")


def _volver(defecto="recepcion.citas"):
    nxt = request.form.get("next") or ""
    permitido = nxt if nxt.startswith(("/recepcion", "/admin")) else None
    return redirect(destino_seguro(permitido, defecto=url_for(defecto)))


@bp.route("/")
@staff
def dashboard():
    h = hoy().isoformat()
    return render_template(
        "recepcion/dashboard.html",
        citas_hoy=cita.buscar({"desde": h, "hasta": h}, asc=True),
        proximas=cita.buscar({"estado": "Pendiente", "desde": (hoy() + timedelta(days=1)).isoformat()},
                             limite=8, asc=True),
        total_pacientes=usuario.contar("paciente"),
        pendientes=cita.conteo_por_estado({})["Pendiente"],
        recientes=recordatorio.recientes(6),
        por_reprogramar=cita.buscar({"reprogramar": 1}, limite=10, asc=True),
        total_reprogramar=cita.contar({"reprogramar": 1}),
    )


# ---------------- Pacientes (HU-01) ----------------
@bp.route("/pacientes")
@staff
def pacientes():
    q = clean(request.args.get("q")) or None
    pag = pagina_actual(usuario.contar_filtrado("paciente", q))
    lista = usuario.listar("paciente", q, limite=pag.per_page, offset=pag.offset)
    if request.args.get("partial"):
        return render_template("recepcion/_pacientes_tabla.html", pacientes=lista, pag=pag)
    return render_template("recepcion/pacientes.html", pacientes=lista, pag=pag)


@bp.route("/pacientes/nuevo", methods=["GET", "POST"])
@staff
def paciente_nuevo():
    if request.method == "POST":
        datos, errores = validar_persona(request.form, "paciente", password_obligatoria=False,
                                         telefono_obligatorio=True)
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"])
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            temporal = None
            if not datos["password"]:
                temporal = datos["password"] = secrets.token_urlsafe(9)
            pid = usuario.crear(datos)
            auditoria.registrar("crear", "usuario", pid, {"rol": "paciente", "password_temporal": bool(temporal)})
            if temporal:
                # Se muestra UNA vez en esta respuesta: no va a flash (cookie) ni se guarda en sesión.
                html = render_template("recepcion/paciente_creado.html", nombre=datos["nombre"],
                                       correo=datos["correo"], temporal=temporal)
                return html, 200, {"Cache-Control": "no-store", "Pragma": "no-cache"}
            flash(f"Paciente '{datos['nombre']}' registrado (HU-01).", "success")
            return redirect(url_for("recepcion.pacientes"))
    return render_template("recepcion/paciente_form.html", p=None, f=request.form)


@bp.route("/pacientes/<int:pid>/editar", methods=["GET", "POST"])
@staff
def paciente_editar(pid):
    p = usuario.get(pid)
    if not p or p["rol"] != "paciente":
        abort(404)
    if request.method == "POST":
        datos, errores = validar_persona(request.form, "paciente", password_obligatoria=False,
                                         telefono_obligatorio=True)
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"], excluir_id=pid)
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            usuario.actualizar(pid, datos)
            auditoria.registrar("editar", "usuario", pid, {"password_cambiada": bool(datos["password"])})
            flash("Datos del paciente actualizados.", "success")
            return redirect(url_for("recepcion.pacientes"))
    return render_template("recepcion/paciente_form.html", p=p, f=request.form or p)


@bp.route("/pacientes/<int:pid>/estado", methods=["POST"])
@staff
def paciente_estado(pid):
    p = usuario.get(pid)
    if not p or p["rol"] != "paciente":
        abort(404)
    usuario.set_activo(pid, not p["activo"])
    auditoria.registrar("activar" if not p["activo"] else "desactivar", "usuario", pid)
    flash(f"Paciente {'activado' if not p['activo'] else 'desactivado'}.", "success")
    return redirect(url_for("recepcion.pacientes"))


@bp.route("/pacientes/<int:pid>/eliminar", methods=["POST"])
@staff
def paciente_eliminar(pid):
    p = usuario.get(pid)
    if not p or p["rol"] != "paciente":
        abort(404)
    if usuario.tiene_citas(pid):
        flash("El paciente tiene citas registradas: no se puede eliminar. Puede desactivarlo.", "warning")
    else:
        usuario.eliminar(pid)
        auditoria.registrar("eliminar", "usuario", pid, {"rol": "paciente"})
        flash("Paciente eliminado.", "success")
    return redirect(url_for("recepcion.pacientes"))


# ---------------- Citas (HU-02, HU-09) ----------------
def _filtros_citas():
    return {
        "q": clean(request.args.get("q")) or None,
        "estado": request.args.get("estado") or None,
        "profesional_id": request.args.get("profesional_id") or None,
        "desde": request.args.get("desde") or None,
        "hasta": request.args.get("hasta") or None,
        "reprogramar": 1 if request.args.get("reprogramar") else None,
    }


@bp.route("/citas")
@staff
def citas():
    f = _filtros_citas()
    pag = pagina_actual(cita.contar(f))
    lista = cita.buscar(f, limite=pag.per_page, offset=pag.offset)
    if request.args.get("partial"):
        return render_template("recepcion/_citas_tabla.html", citas=lista, pag=pag)
    return render_template("recepcion/citas.html", citas=lista, pag=pag, profesionales=usuario.listar("profesional"))


def _form_cita(c=None):
    return render_template("recepcion/cita_form.html", c=c, f=request.form or c or {},
                           pacientes=usuario.listar("paciente", solo_activos=True),
                           profesionales=usuario.listar("profesional", solo_activos=True))


@bp.route("/citas/nueva", methods=["GET", "POST"])
@staff
def cita_nueva():
    if request.method == "POST":
        f = request.form
        motivo = clean(f.get("motivo")) or "Consulta general"
        if len(motivo) > 255:
            flash("El motivo no puede superar 255 caracteres.", "danger")
            return _form_cita()
        cid, error = cita.programar(f.get("paciente_id"), f.get("profesional_id"), f.get("fecha"), f.get("hora"),
                                    motivo)
        if error:
            flash(error, "danger")
        else:
            auditoria.registrar("crear", "cita", cid, {"profesional_id": f.get("profesional_id")})
            notificacion.por_cita(cita.get(cid), "creada")
            flash("Cita agendada sin cruces de horario (HU-02).", "success")
            avisar(recordatorio.enviar_para_cita(cid, "confirmacion"))
            return redirect(url_for("recepcion.citas"))
    return _form_cita()


@bp.route("/citas/<int:cid>/editar", methods=["GET", "POST"])
@staff
def cita_editar(cid):
    c = cita.get(cid) or abort(404)
    if request.method == "POST":
        f = request.form
        motivo = clean(f.get("motivo")) or "Consulta general"
        if len(motivo) > 255:
            flash("El motivo no puede superar 255 caracteres.", "danger")
            return _form_cita(c)
        _, error = cita.programar(f.get("paciente_id"), f.get("profesional_id"), f.get("fecha"), f.get("hora"),
                                  motivo, cita_id=cid)
        if error:
            flash(error, "danger")
        else:
            auditoria.registrar("reprogramar", "cita", cid, {"antes": f"{c['fecha']} {c['hora']}",
                                                              "despues": f"{f.get('fecha')} {f.get('hora')}"})
            flash("Cita actualizada.", "success")
            nueva = cita.get(cid)
            if (nueva["fecha"], nueva["hora"]) != (c["fecha"], c["hora"]):
                notificacion.por_cita(nueva, "reprogramada")
            return redirect(url_for("recepcion.citas"))
    return _form_cita(c)


@bp.route("/citas/<int:cid>/estado", methods=["POST"])
@staff
def cita_estado(cid):
    c = cita.get(cid) or abort(404)
    estado = request.form.get("estado")
    if estado not in ESTADOS:
        abort(400, "Estado inválido.")
    if estado != "Cancelada":
        # B6: recepción solo agenda/cancela; la atención la registra el profesional asignado
        extra = " Como administrador puede usar 'Forzar atención' con motivo." if session.get("rol") == "administrador" else ""
        flash("Recepción solo puede cancelar citas: Atendida e Inasistida las registra el profesional asignado "
              "dentro de su horario." + extra, "warning")
        return _volver()
    try:
        cita.cambiar_estado(cid, estado)
    except IntegrityError:
        flash("No se puede reactivar: ese horario ya está ocupado por otra cita.", "danger")
        return _volver()
    auditoria.registrar("cambiar_estado", "cita", cid, {"de": c["estado"], "a": estado})
    if c["estado"] != estado:
        notificacion.por_cita(c, "cancelada")
    flash(f"Estado de la cita actualizado a '{estado}' (HU-09).", "success")
    return _volver()


@bp.route("/citas/<int:cid>/eliminar", methods=["POST"])
@staff
def cita_eliminar(cid):
    cita.get(cid) or abort(404)
    if historial.notas_de_cita(cid):
        flash("La cita tiene notas clínicas asociadas: no se puede eliminar. Cámbiela a 'Cancelada'.", "warning")
    else:
        try:
            cita.eliminar(cid)
            auditoria.registrar("eliminar", "cita", cid)
            flash("Cita eliminada.", "success")
        except IntegrityError:
            flash("No se puede eliminar la cita.", "warning")
    return _volver()


@bp.route("/citas/<int:cid>/recordatorio", methods=["POST"])
@staff
def cita_recordatorio(cid):
    cita.get(cid) or abort(404)
    avisar(recordatorio.enviar_para_cita(cid, "recordatorio"))
    return _volver()
