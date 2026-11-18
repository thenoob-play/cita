"""Fábrica de la aplicación Flask (arquitectura MVC con Blueprints)."""
import threading
import time

from flask import Flask, jsonify, render_template, request, abort

from config import CLAVES_INSEGURAS, Config
from . import db as database
from .utils import ESTADOS, DIAS, ROLES, csrf_field, csrf_token, csrf_valid, fecha_es


class ConfiguracionInsegura(RuntimeError):
    """La configuración no permite arrancar fuera de desarrollo."""


def _validar_config(app):
    if app.config.get("APP_ENV") == "development" or app.testing:
        return
    clave = app.config.get("SECRET_KEY") or ""
    if clave in CLAVES_INSEGURAS or len(clave) < 16:
        raise ConfiguracionInsegura(
            "SECRET_KEY es obligatoria fuera de desarrollo (mínimo 16 caracteres y distinta de la de ejemplo). "
            "Defínala en .env, por ejemplo con:  python -c \"import secrets; print(secrets.token_hex(32))\"  "
            "o, solo en su equipo de desarrollo, ponga APP_ENV=development.")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    _validar_config(app)
    if app.testing:
        app.config["MAIL_ASYNC"] = False        # pruebas deterministas: el correo se procesa en línea
    database.init_app(app)

    from .controllers import admin, api, auth, correos, cuenta, paciente, profesional, recepcion
    for mod in (auth, admin, recepcion, profesional, paciente, api, correos, cuenta):
        app.register_blueprint(mod.bp)

    app.jinja_env.globals.update(csrf_field=csrf_field, csrf_token=csrf_token,
                                 ESTADOS=ESTADOS, DIAS=DIAS, ROLES=ROLES)
    app.jinja_env.filters["fecha_es"] = fecha_es

    @app.before_request
    def proteger_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not csrf_valid(token):
                abort(400, "El formulario expiró o es inválido. Recargue la página e intente de nuevo.")

    @app.context_processor
    def inyectar():
        from flask import session
        from .models import notificacion, recordatorio
        from .utils import ahora
        datos = {"smtp_activo": recordatorio.smtp_configurado(), "modo_dev": app.config.get("DEV_MODE", False),
                 "notif_no_leidas": 0, "notif_recientes": [], "fecha_hoy": ahora()}
        if session.get("user_id"):
            try:   # la campana nunca debe impedir que se muestre una página (p. ej. la de error de BD)
                datos["notif_no_leidas"] = notificacion.no_leidas(session["user_id"])
                datos["notif_recientes"] = notificacion.listar(session["user_id"], limite=6)
            except Exception:
                pass
        return datos

    # ---------- Manejo de errores ----------
    def _error(code, titulo, mensaje):
        if request.path.startswith("/api/"):
            return jsonify(error=mensaje), code
        return render_template("errors/error.html", code=code, titulo=titulo, mensaje=mensaje), code

    @app.errorhandler(400)
    def e400(e):
        return _error(400, "Solicitud no válida", getattr(e, "description", "Solicitud no válida."))

    @app.errorhandler(403)
    def e403(e):
        return _error(403, "Acceso denegado", "No tiene permisos para acceder a este recurso.")

    @app.errorhandler(404)
    def e404(e):
        return _error(404, "Página no encontrada", "El recurso que busca no existe.")

    @app.errorhandler(405)
    def e405(e):
        return _error(405, "Método no permitido", "La operación solicitada no está permitida.")

    @app.errorhandler(database.DatabaseUnavailable)
    def edb(e):
        app.logger.error("BD no disponible: %s", e)
        return _error(503, "Base de datos no disponible",
                      f"No se pudo conectar a la base de datos: {e}. Revise la configuración en .env "
                      "y confirme que el servidor MySQL esté encendido si usa DB_ENGINE=mysql.")

    @app.errorhandler(500)
    def e500(e):
        return _error(500, "Error interno", "Ocurrió un error inesperado. Intente de nuevo.")

    if app.config.get("AUTO_REMINDERS"):
        _iniciar_recordatorios_automaticos(app)
    return app


def _iniciar_recordatorios_automaticos(app):
    """Hilo en segundo plano: cada hora encola y envía los recordatorios de las citas de mañana."""
    import os
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    def bucle():
        from .models import recordatorio
        while True:
            try:
                with app.app_context():
                    recordatorio.procesar_pendientes(sincrono=True)
                    n = recordatorio.enviar_manana(sincrono=True)
                    if n:
                        app.logger.info("Recordatorios automáticos procesados: %s", n)
            except Exception as exc:  # no detener el hilo
                app.logger.warning("Recordatorios automáticos: %s", exc)
            time.sleep(3600)

    threading.Thread(target=bucle, daemon=True, name="recordatorios").start()
