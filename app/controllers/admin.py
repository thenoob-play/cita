import calendar
import csv
import io
from datetime import timedelta

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template, request,
                   session, url_for)

from ..db import IntegrityError, get_db
from ..models import auditoria, cita, especialidad, excepcion, horario, notificacion, recordatorio, usuario
from ..services import agenda as agenda_srv
from ..utils import ROLES, ahora, clean, hoy, pagina_actual, parse_fecha, parse_hora, role_required, volver
from ..validators import validar_persona

bp = Blueprint("admin", __name__, url_prefix="/admin")
solo_admin = role_required("administrador")


def _rango(periodo, desde, hasta):
    h = hoy()          # "hoy" en la zona horaria del negocio (TZ)
    if periodo == "hoy":
        return h, h
    if periodo == "proximos7":
        return h, h + timedelta(days=7)
    if periodo == "ultimos7":
        return h - timedelta(days=7), h
    if periodo == "mes":
        return h.replace(day=1), h.replace(day=calendar.monthrange(h.year, h.month)[1])
    if periodo == "rango":
        return desde or None, hasta or None
    return None, None


def _filtros():
    periodo = request.args.get("periodo", "todos")
    d, h = _rango(periodo, request.args.get("desde"), request.args.get("hasta"))
    f = {
        "desde": d.isoformat() if hasattr(d, "isoformat") else d,
        "hasta": h.isoformat() if hasattr(h, "isoformat") else h,
        "profesional_id": request.args.get("profesional_id") or None,
        "estado": request.args.get("estado") or None,
        "q": clean(request.args.get("q")) or None,
    }
    return periodo, f


# ---------------- Dashboard y reportes (HU-10) ----------------
@bp.route("/")
@solo_admin
def dashboard():
    periodo, f = _filtros()
    limite = 500
    ctx = dict(
        citas=cita.buscar(f, limite=limite), total_filtro=cita.contar(f), limite_tabla=limite,
        por_estado=cita.conteo_por_estado(f), por_prof=cita.conteo_por_profesional(f), periodo=periodo,
    )
    if request.args.get("partial"):
        return render_template("admin/_reporte.html", **ctx)
    todas = cita.conteo_por_estado({})
    ctx.update(
        profesionales=usuario.listar("profesional"),
        total_citas=sum(todas.values()), pendientes=todas["Pendiente"],
        total_pacientes=usuario.contar("paciente"), total_profesionales=usuario.contar("profesional"),
        recientes=recordatorio.recientes(),
    )
    return render_template("admin/dashboard.html", **ctx)


@bp.route("/reporte.csv")
@solo_admin
def reporte_csv():
    _, f = _filtros()
    maximo = current_app.config["REPORT_MAX_ROWS"]
    filas = cita.buscar(f, limite=maximo + 1)
    truncado = len(filas) > maximo
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Fecha", "Hora", "Paciente", "Documento", "Profesional", "Especialidad", "Motivo", "Estado"])
    for c in filas[:maximo]:
        w.writerow([c["id"], c["fecha"], c["hora"], c["paciente_nombre"], c["paciente_documento"],
                    c["profesional_nombre"], c["especialidad"] or "", c["motivo"], c["estado"]])
    if truncado:
        w.writerow([f"AVISO: reporte truncado a {maximo} filas de {cita.contar(f)}. Refine los filtros "
                    "(periodo, profesional o estado) para exportar el resto."])
    data = "﻿" + out.getvalue()  # BOM para que Excel respete tildes
    headers = {"Content-Disposition": "attachment; filename=reporte_citas.csv"}
    if truncado:
        headers["X-Reporte-Truncado"] = str(maximo)
    return Response(data, mimetype="text/csv; charset=utf-8", headers=headers)


@bp.route("/recordatorios/enviar-manana", methods=["POST"])
@solo_admin
def recordatorios_manana():
    n = recordatorio.enviar_manana()          # encola y despacha en segundo plano
    modo = "por correo (SMTP)" if recordatorio.smtp_configurado() else "en modo demostración (SMTP no configurado)"
    flash(f"Recordatorios de mañana {modo}: {n} enviados a la cola de correo. "
          "El resultado de cada envío aparece en 'Últimos correos registrados'.", "success")
    return redirect(url_for("admin.dashboard"))


# ---------------- Usuarios (CRUD) ----------------
@bp.route("/usuarios")
@solo_admin
def usuarios():
    rol = request.args.get("rol") or None
    rol = rol if rol in ROLES else None
    q = clean(request.args.get("q")) or None
    pag = pagina_actual(usuario.contar_filtrado(rol, q))
    lista = usuario.listar(rol, q, limite=pag.per_page, offset=pag.offset)
    if request.args.get("partial"):
        return render_template("admin/_usuarios_tabla.html", usuarios=lista, pag=pag)
    return render_template("admin/usuarios.html", usuarios=lista, pag=pag)


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@solo_admin
def usuario_nuevo():
    if request.method == "POST":
        rol = request.form.get("rol")
        if rol not in ROLES:
            abort(400, "Rol inválido.")
        datos, errores = validar_persona(request.form, rol)
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"])
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            uid = usuario.crear(datos)
            auditoria.registrar("crear", "usuario", uid, {"rol": rol})
            flash(f"Usuario '{datos['nombre']}' creado como {rol}.", "success")
            if rol == "profesional":
                flash("Ahora defina su horario de atención.", "info")
                return redirect(url_for("admin.horarios", pid=uid))
            return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", u=None, f=request.form,
                           especialidades=especialidad.listar(),
                           rol_inicial=request.args.get("rol", "profesional"))


@bp.route("/usuarios/<int:uid>/editar", methods=["GET", "POST"])
@solo_admin
def usuario_editar(uid):
    u = usuario.get(uid) or abort(404)
    if request.method == "POST":
        datos, errores = validar_persona(request.form, u["rol"], password_obligatoria=False)
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"], excluir_id=uid)
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            usuario.actualizar(uid, datos)
            auditoria.registrar("editar", "usuario", uid, {"password_cambiada": bool(datos["password"])})
            flash("Usuario actualizado correctamente.", "success")
            return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", u=u, f=request.form or u,
                           especialidades=especialidad.listar(), rol_inicial=u["rol"])


@bp.route("/usuarios/<int:uid>/estado", methods=["POST"])
@solo_admin
def usuario_estado(uid):
    u = usuario.get(uid) or abort(404)
    if uid == session["user_id"]:
        flash("No puede desactivar su propia cuenta.", "warning")
    else:
        db = get_db()
        with db.transaction():
            db.lock_profesional(uid)
            usuario.set_activo(uid, not u["activo"])
            auditoria.registrar("activar" if not u["activo"] else "desactivar", "usuario", uid, {"rol": u["rol"]})
            # B9: un profesional desactivado deja sus citas futuras pendientes para reprogramar
            marcadas = (agenda_srv.marcar_futuras_de_profesional(uid, "profesional desactivado")
                        if u["activo"] and u["rol"] == "profesional" else 0)
        flash(f"Usuario {'activado' if not u['activo'] else 'desactivado'}.", "success")
        if marcadas:
            flash(f"{marcadas} cita(s) futuras del profesional quedaron marcadas para reprogramación.", "warning")
            notificacion.a_roles(("recepcionista", "administrador"), "Citas por reprogramar",
                                 f"{marcadas} cita(s) de {u['nombre']} requieren reprogramación (profesional desactivado).",
                                 url_for("recepcion.citas", reprogramar=1), "alerta", excluir=session["user_id"])
    return volver("admin.usuarios")


@bp.route("/usuarios/<int:uid>/eliminar", methods=["POST"])
@solo_admin
def usuario_eliminar(uid):
    u = usuario.get(uid) or abort(404)
    if uid == session["user_id"]:
        flash("No puede eliminar su propia cuenta.", "warning")
    elif usuario.tiene_citas(uid):
        flash("El usuario tiene citas asociadas: no se puede eliminar. Puede desactivarlo.", "warning")
    else:
        try:
            usuario.eliminar(uid)
            auditoria.registrar("eliminar", "usuario", uid, {"rol": u["rol"]})
            flash("Usuario eliminado.", "success")
        except IntegrityError:
            flash("No se puede eliminar: tiene registros relacionados. Desactívelo.", "warning")
    return redirect(url_for("admin.usuarios"))


# ---------------- Horarios de profesionales (HU-05) con vigencia ----------------
def _profesional(pid):
    p = usuario.get(pid)
    if not p or p["rol"] != "profesional":
        abort(404)
    return p


def _confirmar():
    return request.form.get("confirmar") == "1"


def _resolver(p, cambio, motivo, ok_msg, volver_a):
    """Aplica un cambio de agenda con análisis de impacto (B4) y responde según el resultado."""
    estado, afectadas, error = agenda_srv.aplicar_cambio(p["id"], cambio, _confirmar(), motivo)
    if estado == "error":
        flash(error, "danger")
        return redirect(volver_a)
    if estado == "confirmar":
        campos = {k: v for k, v in request.form.items() if k not in ("_csrf", "confirmar")}
        return render_template("admin/impacto.html", p=p, afectadas=afectadas, campos=campos,
                               accion=request.path, descripcion=motivo, volver_a=volver_a), 409
    flash(ok_msg, "success")
    if afectadas:
        flash(f"{len(afectadas)} cita(s) quedaron marcadas como 'requiere reprogramación': recepción debe "
              "reagendarlas y el profesional no puede atenderlas.", "warning")
    return redirect(volver_a)


def _leer_bloque(form):
    """Valida día y horas de un bloque. Devuelve (dia, ini, fin, error)."""
    dia, ini, fin = form.get("dia_semana", ""), parse_hora(form.get("hora_inicio")), parse_hora(form.get("hora_fin"))
    if not dia.isdigit() or not 0 <= int(dia) <= 6 or not ini or not fin:
        return None, None, None, "Día u horas inválidos."
    if fin <= ini:
        return None, None, None, ("La hora de fin debe ser posterior a la de inicio "
                                  "(no se permiten turnos que crucen la medianoche).")
    return int(dia), ini, fin, None


def _cerrar_desde(viejo):
    """Primer día en que el bloque deja de regir: hoy (o su inicio, si aún no empezaba)."""
    h = hoy()
    if not viejo or (viejo["vigente_hasta"] and viejo["vigente_hasta"] < h.isoformat()):
        raise agenda_srv.Rechazo("Ese bloque ya no está vigente.")
    return max(h, parse_fecha(viejo["vigente_desde"]) or h)


@bp.route("/profesionales/<int:pid>/horarios", methods=["GET", "POST"])
@solo_admin
def horarios(pid):
    p = _profesional(pid)
    volver_a = url_for("admin.horarios", pid=pid)
    if request.method == "POST":
        dia, ini, fin, error = _leer_bloque(request.form)
        desde = parse_fecha(request.form.get("vigente_desde")) or hoy()
        hasta = parse_fecha(request.form.get("vigente_hasta")) if request.form.get("vigente_hasta") else None
        if not error and desde < hoy():
            error = "La vigencia no puede empezar en el pasado (no se alteran citas pasadas)."
        if not error and request.form.get("vigente_hasta") and (not hasta or hasta < desde):
            error = "La fecha final de vigencia debe ser igual o posterior a la inicial."
        if error:
            flash(error, "danger")
            return redirect(volver_a)
        desde_iso, hasta_iso = desde.isoformat(), (hasta.isoformat() if hasta else None)

        def cambio():
            if horario.solapa(pid, dia, ini, fin, desde_iso, hasta_iso):
                raise agenda_srv.Rechazo("El bloque se cruza con otro horario ya definido ese día en la misma vigencia.")
            hid = horario.agregar(pid, dia, ini, fin, desde_iso, hasta_iso)
            auditoria.registrar("crear", "horario", hid, {"profesional_id": pid, "dia": dia, "ini": ini, "fin": fin,
                                                           "desde": desde_iso, "hasta": hasta_iso})
        return _resolver(p, cambio, "nuevo bloque de horario", "Bloque de atención agregado.", volver_a)
    historial = bool(request.args.get("historial"))
    return render_template("admin/horarios.html", p=p, horarios=horario.listar(pid, hoy().isoformat(), historial),
                           historial=historial, hoy=hoy().isoformat(), tab="semanal")


@bp.route("/profesionales/<int:pid>/horarios/<int:hid>/editar", methods=["POST"])
@solo_admin
def horario_editar(pid, hid):
    """Editar NO modifica el registro: cierra el bloque (vigente_hasta = día anterior) y crea otro desde hoy."""
    p = _profesional(pid)
    volver_a = url_for("admin.horarios", pid=pid)
    dia, ini, fin, error = _leer_bloque(request.form)
    if error:
        flash(error, "danger")
        return redirect(volver_a)

    def cambio():
        viejo = horario.get(hid, pid)
        desde = _cerrar_desde(viejo)
        cierre = (desde - timedelta(days=1)).isoformat()
        horario.cerrar(hid, pid, cierre)
        if horario.solapa(pid, dia, ini, fin, desde.isoformat(), viejo["vigente_hasta"]):
            raise agenda_srv.Rechazo("El bloque se cruza con otro horario ya definido ese día en la misma vigencia.")
        nuevo = horario.agregar(pid, dia, ini, fin, desde.isoformat(), viejo["vigente_hasta"])
        auditoria.registrar("editar", "horario", hid, {
            "profesional_id": pid, "cerrado_hasta": cierre, "nuevo_id": nuevo,
            "antes": f"{viejo['dia_semana']} {viejo['hora_inicio']}-{viejo['hora_fin']}",
            "despues": f"{dia} {ini[:5]}-{fin[:5]}"})
    return _resolver(p, cambio, "edición de bloque de horario",
                     "Bloque actualizado: el anterior quedó cerrado y el nuevo rige desde hoy.", volver_a)


@bp.route("/profesionales/<int:pid>/horarios/<int:hid>/eliminar", methods=["POST"])
@solo_admin
def horario_eliminar(pid, hid):
    """Eliminar = cerrar la vigencia (el registro se conserva para el historial)."""
    p = _profesional(pid)

    def cambio():
        desde = _cerrar_desde(horario.get(hid, pid))
        cierre = (desde - timedelta(days=1)).isoformat()
        horario.cerrar(hid, pid, cierre)
        auditoria.registrar("cerrar", "horario", hid, {"profesional_id": pid, "cerrado_hasta": cierre})
    return _resolver(p, cambio, "eliminación de bloque de horario",
                     "Bloque de atención eliminado (cerrado desde hoy; se conserva en el historial).",
                     url_for("admin.horarios", pid=pid))


# ---------------- Excepciones de horario (bloqueos y turnos extra) ----------------
@bp.route("/profesionales/<int:pid>/excepciones", methods=["GET", "POST"])
@solo_admin
def excepciones(pid):
    p = _profesional(pid)
    volver_a = url_for("admin.excepciones", pid=pid)
    if request.method == "POST":
        f = request.form
        fecha, tipo, motivo = parse_fecha(f.get("fecha")), f.get("tipo"), clean(f.get("motivo"))
        dia_completo = tipo == "bloqueo" and f.get("dia_completo") == "1"
        ini, fin = (None, None) if dia_completo else (parse_hora(f.get("hora_inicio")), parse_hora(f.get("hora_fin")))
        error = None
        if not fecha or fecha < hoy():
            error = "Indique una fecha de hoy en adelante."
        elif tipo not in ("bloqueo", "extra"):
            error = "Tipo de excepción inválido."
        elif not dia_completo and (not ini or not fin):
            error = "Indique hora de inicio y fin (o marque 'día completo' para un bloqueo)."
        elif not dia_completo and fin <= ini:
            error = "La hora de fin debe ser posterior a la de inicio (no se permiten turnos que crucen la medianoche)."
        elif not 3 <= len(motivo) <= 255:
            error = "Indique el motivo (3 a 255 caracteres)."
        if error:
            flash(error, "danger")
            return redirect(volver_a)
        fecha_iso = fecha.isoformat()

        def cambio():
            if excepcion.solapa(pid, fecha_iso, tipo, ini, fin):
                raise agenda_srv.Rechazo(f"Ya existe un {tipo} que se cruza con ese horario el {fecha_iso}.")
            eid = excepcion.agregar(pid, fecha_iso, tipo, ini, fin, motivo, session["user_id"])
            auditoria.registrar("crear", "excepcion_horario", eid, {"profesional_id": pid, "fecha": fecha_iso,
                                                                     "tipo": tipo, "ini": ini, "fin": fin,
                                                                     "motivo": motivo})
        etiqueta = "Bloqueo registrado." if tipo == "bloqueo" else "Turno extra registrado."
        return _resolver(p, cambio, f"{tipo} de agenda", etiqueta, volver_a)
    return render_template("admin/excepciones.html", p=p, excepciones=excepcion.listar(pid, hoy().isoformat()),
                           hoy=hoy().isoformat(), tab="excepciones")


@bp.route("/profesionales/<int:pid>/excepciones/<int:eid>/eliminar", methods=["POST"])
@solo_admin
def excepcion_eliminar(pid, eid):
    p = _profesional(pid)

    def cambio():
        e = excepcion.get(eid, pid)
        if not e:
            raise agenda_srv.Rechazo("La excepción no existe.")
        excepcion.eliminar(eid, pid)
        auditoria.registrar("eliminar", "excepcion_horario", eid, {"profesional_id": pid, "fecha": e["fecha"],
                                                                    "tipo": e["tipo"]})
    return _resolver(p, cambio, "eliminación de excepción", "Excepción eliminada.",
                     url_for("admin.excepciones", pid=pid))


# ---------------- Override de atención (B6) ----------------
@bp.route("/citas/<int:cid>/atencion", methods=["GET", "POST"])
@solo_admin
def atencion_forzada(cid):
    """El administrador puede registrar una atención fuera de la regla, con motivo obligatorio (override=1)."""
    c = cita.get(cid) or abort(404)
    _, bloqueo = agenda_srv.puede_atender(c, usuario.get(c["profesional_id"]), ahora())
    if request.method == "POST":
        estado, motivo = request.form.get("estado"), clean(request.form.get("motivo"))
        if estado not in agenda_srv.ESTADOS_ATENCION:
            abort(400, "Estado inválido.")
        if not 5 <= len(motivo) <= 255:
            flash("El motivo del override es obligatorio (5 a 255 caracteres).", "danger")
        else:
            try:
                cita.cambiar_estado(cid, estado)
                auditoria.registrar("forzar_atencion", "cita", cid, {"de": c["estado"], "a": estado, "motivo": motivo,
                                                                     "regla_incumplida": bloqueo or None},
                                    override=True)
                if estado != c["estado"]:
                    notificacion.por_cita(c, estado.lower())
                flash(f"Atención registrada como '{estado}' por override de administrador (queda en auditoría).",
                      "success")
                return redirect(url_for("recepcion.citas"))
            except IntegrityError:
                flash("No se puede reactivar: ese horario ya está ocupado por otra cita.", "danger")
    return render_template("admin/atencion_forzada.html", c=c, bloqueo=bloqueo,
                           estados=agenda_srv.ESTADOS_ATENCION)


# ---------------- Especialidades (CRUD) ----------------
@bp.route("/especialidades", methods=["GET", "POST"])
@solo_admin
def especialidades():
    if request.method == "POST":
        nombre = clean(request.form.get("nombre"))
        if len(nombre) < 3 or len(nombre) > 100:
            flash("El nombre debe tener entre 3 y 100 caracteres.", "danger")
        else:
            try:
                especialidad.crear(nombre)
                flash("Especialidad creada.", "success")
            except IntegrityError:
                flash("Esa especialidad ya existe.", "danger")
        return redirect(url_for("admin.especialidades"))
    return render_template("admin/especialidades.html", lista=especialidad.listar())


@bp.route("/especialidades/<int:eid>/editar", methods=["POST"])
@solo_admin
def especialidad_editar(eid):
    especialidad.get(eid) or abort(404)
    nombre = clean(request.form.get("nombre"))
    if len(nombre) < 3:
        flash("Nombre demasiado corto.", "danger")
    else:
        try:
            especialidad.renombrar(eid, nombre)
            flash("Especialidad actualizada.", "success")
        except IntegrityError:
            flash("Ya existe una especialidad con ese nombre.", "danger")
    return redirect(url_for("admin.especialidades"))


@bp.route("/especialidades/<int:eid>/eliminar", methods=["POST"])
@solo_admin
def especialidad_eliminar(eid):
    e = next((x for x in especialidad.listar() if x["id"] == eid), None) or abort(404)
    if e["profesionales"]:
        flash("Hay profesionales con esta especialidad: no se puede eliminar.", "warning")
    else:
        especialidad.eliminar(eid)
        flash("Especialidad eliminada.", "success")
    return redirect(url_for("admin.especialidades"))
