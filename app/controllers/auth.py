import secrets

from flask import (Blueprint, current_app, flash, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash

from ..models import auditoria, notificacion, recordatorio, seguridad, usuario
from ..utils import ahora, clean, home_for
from ..validators import validar_persona

bp = Blueprint("auth", __name__)

MSG_LOGIN = "Correo o contraseña incorrectos, o la cuenta está inactiva."
MSG_BLOQUEO = "Demasiados intentos fallidos. Espere unos minutos e intente de nuevo."
MSG_RECUPERAR = ("Si el correo está registrado y activo, recibirá un enlace para restablecer la contraseña. "
                 "El enlace vence en {min} minutos y sirve una sola vez.")


def _ip():
    return request.remote_addr or "desconocida"


@bp.route("/")
def index():
    if "user_id" in session:
        return redirect(home_for(session.get("rol")))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(home_for(session.get("rol")))
    if request.method == "POST":
        correo = clean(request.form.get("correo")).lower()
        password = request.form.get("password") or ""
        if seguridad.bloqueado(correo, _ip()):
            flash(MSG_BLOQUEO, "danger")
            return render_template("auth/login.html"), 429
        u = usuario.por_correo(correo)
        if u and u["activo"] and check_password_hash(u["password_hash"], password):
            seguridad.limpiar_intentos(correo, _ip())
            session.clear()
            session.permanent = True
            session.update(user_id=u["id"], nombre=u["nombre"], rol=u["rol"], _csrf=secrets.token_hex(16),
                           acceso_anterior=u.get("ultimo_acceso"))
            usuario.registrar_acceso(u["id"], ahora().strftime("%Y-%m-%d %H:%M:%S"))
            flash(f"¡Bienvenido(a), {u['nombre']}!", "success")
            return redirect(home_for(u["rol"]))
        seguridad.registrar_fallo(correo, _ip())
        flash(MSG_LOGIN, "danger")
    return render_template("auth/login.html")


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    """Auto-registro de pacientes."""
    if "user_id" in session:
        return redirect(home_for(session.get("rol")))
    datos = {}
    if request.method == "POST":
        datos, errores = validar_persona(request.form, "paciente", telefono_obligatorio=True)
        if not errores:
            errores = usuario.duplicados(datos["documento"], datos["correo"])
        if errores:
            for e in errores:
                flash(e, "danger")
        else:
            uid = usuario.crear(datos)
            auditoria.registrar("crear", "usuario", uid, {"rol": "paciente", "origen": "autoregistro"}, usuario_id=uid)
            notificacion.crear(uid, "¡Bienvenido(a) a CitasMédicas!",
                               "Ya puede solicitar su primera cita en línea desde «Mis citas».",
                               url_for("paciente.dashboard"), "exito")
            flash("Registro exitoso. Ya puede iniciar sesión.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/registro.html", f=datos or request.form)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada exitosamente.", "info")
    return redirect(url_for("auth.login"))


# ---------------- Recuperación de contraseña ----------------
def _enviar_enlace(destino, enlace):
    minutos = current_app.config["RESET_TOKEN_MIN"]
    cuerpo = (f"Recibimos una solicitud para restablecer su contraseña.\n\nAbra este enlace (vence en {minutos} "
              f"minutos y sirve una sola vez):\n{enlace}\n\nSi usted no lo solicitó, ignore este mensaje.\n\n"
              "Sistema de Gestión de Citas Médicas - UCC")
    recordatorio.enviar_smtp(destino, "Restablecer contraseña", cuerpo)


@bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    """Respuesta idéntica exista o no el correo (no revela cuentas). El token no se guarda en sesión."""
    if request.method == "POST":
        correo = clean(request.form.get("correo")).lower()
        enlace_demo = None
        if seguridad.bloqueado(correo, _ip()):
            flash(MSG_BLOQUEO, "danger")
            return render_template("auth/recuperar.html"), 429
        seguridad.registrar_fallo(correo, _ip())     # cuenta como intento: limita el abuso del formulario
        u = usuario.por_correo(correo)
        if u and u["activo"]:
            token = seguridad.crear_token(u["id"])
            enlace = url_for("auth.restablecer", token=token, _external=True)
            auditoria.registrar("solicitar_recuperacion", "usuario", u["id"], usuario_id=u["id"])
            if recordatorio.smtp_configurado():
                recordatorio.en_segundo_plano(_enviar_enlace, u["correo"], enlace)
            elif current_app.config.get("DEV_MODE"):
                enlace_demo = enlace          # solo en desarrollo y solo en esta respuesta
        resp = render_template("auth/recuperar.html", enviado=True,
                               mensaje=MSG_RECUPERAR.format(min=current_app.config["RESET_TOKEN_MIN"]),
                               enlace_demo=enlace_demo)
        return resp, 200, {"Cache-Control": "no-store"}
    return render_template("auth/recuperar.html")


@bp.route("/restablecer/<token>", methods=["GET", "POST"])
def restablecer(token):
    t = seguridad.token_vigente(token)
    if not t:
        flash("El enlace no es válido, ya se usó o venció. Solicite uno nuevo.", "warning")
        return redirect(url_for("auth.recuperar"))
    if request.method == "POST":
        pw, pw2 = request.form.get("password") or "", request.form.get("password2") or ""
        if len(pw) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.", "danger")
        elif pw != pw2:
            flash("Las contraseñas no coinciden.", "danger")
        elif not seguridad.consumir_token(t["id"]):
            flash("El enlace ya se usó. Solicite uno nuevo.", "warning")
            return redirect(url_for("auth.recuperar"))
        else:
            usuario.set_password(t["usuario_id"], pw)
            u = usuario.get(t["usuario_id"])
            seguridad.limpiar_intentos(u["correo"])
            auditoria.registrar("restablecer_password", "usuario", u["id"], usuario_id=u["id"])
            flash("Contraseña actualizada. Ya puede iniciar sesión.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/restablecer.html", token=token), 200, {"Cache-Control": "no-store",
                                                                          "Referrer-Policy": "no-referrer"}
