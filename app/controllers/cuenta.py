"""Mi cuenta (todos los roles) y centro de notificaciones."""
import json

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash

from ..models import auditoria, cita, notificacion, usuario
from ..utils import ahora, destino_seguro, pagina_actual, role_required
from ..validators import validar_persona

bp = Blueprint("cuenta", __name__)
logueado = role_required()


# ---------------- Mi cuenta ----------------
@bp.route("/cuenta")
@logueado
def ver():
    uid = session["user_id"]
    u = usuario.get(uid)
    resumen = None
    if u["rol"] == "paciente":
        resumen = cita.conteo_por_estado({"paciente_id": uid})
    elif u["rol"] == "profesional":
        resumen = cita.conteo_por_estado({"profesional_id": uid})
    return render_template("cuenta/cuenta.html", u=u, f=request.form or u, resumen=resumen,
                           actividad=auditoria.de_usuario(uid),
                           acceso_anterior=session.get("acceso_anterior"),
                           tab=request.args.get("tab", "perfil"))


@bp.route("/cuenta/perfil", methods=["POST"])
@logueado
def perfil():
    u = usuario.get(session["user_id"])
    form = request.form.to_dict()
    form["documento"] = u["documento"]                       # el documento no se modifica
    form["especialidad_id"] = str(u["especialidad_id"] or "")  # la especialidad la asigna el administrador
    form.pop("password", None)
    datos, errores = validar_persona(form, u["rol"], password_obligatoria=False,
                                     telefono_obligatorio=u["rol"] == "paciente")
    if not errores:
        errores = usuario.duplicados(datos["documento"], datos["correo"], excluir_id=u["id"])
    if errores:
        for e in errores:
            flash(e, "danger")
        return render_template("cuenta/cuenta.html", u=u, f=request.form, resumen=None,
                               actividad=auditoria.de_usuario(u["id"]),
                               acceso_anterior=session.get("acceso_anterior"), tab="perfil"), 400
    usuario.actualizar(u["id"], datos)
    auditoria.registrar("editar", "usuario", u["id"], {"origen": "mi_cuenta"})
    session["nombre"] = datos["nombre"]
    flash("Sus datos fueron actualizados.", "success")
    return redirect(url_for("cuenta.ver"))


@bp.route("/cuenta/password", methods=["POST"])
@logueado
def password():
    u = usuario.get(session["user_id"])
    actual = request.form.get("password_actual", "")
    nueva, nueva2 = request.form.get("password", ""), request.form.get("password2", "")
    if not check_password_hash(u["password_hash"], actual):
        flash("La contraseña actual no es correcta.", "danger")
    elif len(nueva) < 6:
        flash("La nueva contraseña debe tener al menos 6 caracteres.", "danger")
    elif nueva != nueva2:
        flash("Las contraseñas no coinciden.", "danger")
    elif nueva == actual:
        flash("La nueva contraseña debe ser distinta de la actual.", "warning")
    else:
        usuario.set_password(u["id"], nueva)
        auditoria.registrar("cambiar_password", "usuario", u["id"])
        notificacion.crear(u["id"], "Contraseña actualizada",
                           "La contraseña de su cuenta se cambió. Si no fue usted, contacte al administrador.",
                           url_for("cuenta.ver", tab="seguridad"), "alerta")
        flash("Contraseña actualizada correctamente.", "success")
    return redirect(url_for("cuenta.ver", tab="seguridad"))


@bp.route("/cuenta/mis-datos.json")
@logueado
def exportar():
    """Descarga de los datos personales propios (derecho de acceso, Ley 1581 de 2012)."""
    uid = session["user_id"]
    u = usuario.get(uid)
    perfil_ = {k: u[k] for k in ("nombre", "documento", "telefono", "correo", "rol", "especialidad",
                                 "created_at", "ultimo_acceso")}
    citas = []
    if u["rol"] == "paciente":
        citas = [{k: c[k] for k in ("fecha", "hora", "estado", "motivo", "profesional_nombre", "especialidad")}
                 for c in cita.buscar({"paciente_id": uid}, limite=1000)]
    auditoria.registrar("exportar_datos", "usuario", uid)
    cuerpo = json.dumps({"generado": ahora().strftime("%Y-%m-%d %H:%M"), "perfil": perfil_, "citas": citas},
                        ensure_ascii=False, indent=2, default=str)
    return Response(cuerpo, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=mis_datos.json",
                             "Cache-Control": "no-store"})


# ---------------- Notificaciones ----------------
@bp.route("/notificaciones")
@logueado
def notificaciones():
    uid = session["user_id"]
    solo = request.args.get("filtro") == "no_leidas"
    pag = pagina_actual(notificacion.contar(uid, solo))
    return render_template("cuenta/notificaciones.html", pag=pag, solo=solo,
                           items=notificacion.listar(uid, solo, pag.per_page, pag.offset),
                           total_no_leidas=notificacion.no_leidas(uid))


@bp.route("/notificaciones/resumen")
@logueado
def resumen():
    """JSON para la campana (consulta periódica desde JavaScript)."""
    uid = session["user_id"]
    items = [{"id": n["id"], "titulo": n["titulo"], "mensaje": n["mensaje"], "icono": n["icono"],
              "clase": n["clase"], "leida": bool(n["leida"]), "fecha": n["created_at"][:16],
              "abrir": url_for("cuenta.abrir", nid=n["id"])}
             for n in notificacion.listar(uid, limite=6)]
    return jsonify(no_leidas=notificacion.no_leidas(uid), items=items)


@bp.route("/notificaciones/<int:nid>/abrir", methods=["POST"])
@logueado
def abrir(nid):
    n = notificacion.get(nid, session["user_id"]) or abort(404)
    notificacion.marcar_leida(nid, session["user_id"])
    return redirect(destino_seguro(n["url"], defecto=url_for("cuenta.notificaciones")))


@bp.route("/notificaciones/<int:nid>/leida", methods=["POST"])
@logueado
def leida(nid):
    notificacion.get(nid, session["user_id"]) or abort(404)
    notificacion.marcar_leida(nid, session["user_id"])
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, no_leidas=notificacion.no_leidas(session["user_id"]))
    return redirect(destino_seguro(request.referrer, defecto=url_for("cuenta.notificaciones")))


@bp.route("/notificaciones/leer-todas", methods=["POST"])
@logueado
def leer_todas():
    n = notificacion.marcar_todas(session["user_id"])
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, no_leidas=0)
    flash(f"{n} notificación(es) marcadas como leídas." if n else "No tenía notificaciones sin leer.", "info")
    return redirect(destino_seguro(request.referrer, defecto=url_for("cuenta.notificaciones")))


@bp.route("/notificaciones/<int:nid>/eliminar", methods=["POST"])
@logueado
def eliminar(nid):
    if not notificacion.eliminar(nid, session["user_id"]):
        abort(404)
    flash("Notificación eliminada.", "info")
    return redirect(destino_seguro(request.referrer, defecto=url_for("cuenta.notificaciones")))


@bp.route("/notificaciones/limpiar", methods=["POST"])
@logueado
def limpiar():
    n = notificacion.limpiar_leidas(session["user_id"])
    flash(f"Se eliminaron {n} notificación(es) leídas.", "info")
    return redirect(url_for("cuenta.notificaciones"))
