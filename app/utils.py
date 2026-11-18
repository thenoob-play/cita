"""Decoradores de acceso, CSRF, reloj de negocio, redirecciones seguras y paginación."""
import hmac
import math
import re
import secrets
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from flask import abort, current_app, flash, has_app_context, redirect, request, session, url_for
from markupsafe import Markup

ESTADOS = ["Pendiente", "Atendida", "Cancelada", "Inasistida"]
ROLES = ["administrador", "recepcionista", "profesional", "paciente"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

ROLE_HOME = {
    "administrador": "admin.dashboard",
    "recepcionista": "recepcion.dashboard",
    "profesional": "profesional.agenda",
    "paciente": "paciente.dashboard",
}


def home_for(rol):
    return url_for(ROLE_HOME.get(rol, "auth.login"))


def clean(valor):
    return (valor or "").strip()


# ---------- Acceso ----------
def role_required(*roles):
    """Exige sesión activa y uno de los roles. Revalida que el usuario siga activo."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            from .models import usuario  # import tardío para evitar ciclos
            if "user_id" not in session:
                flash("Inicie sesión para continuar.", "warning")
                return redirect(url_for("auth.login"))
            u = usuario.get(session["user_id"])
            if not u or not u["activo"]:
                session.clear()
                flash("Su cuenta no está disponible. Contacte al administrador.", "danger")
                return redirect(url_for("auth.login"))
            session["rol"], session["nombre"] = u["rol"], u["nombre"]
            if roles and u["rol"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


# ---------- CSRF ----------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def csrf_field():
    return Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">')


def csrf_valid(token):
    return bool(token) and hmac.compare_digest(str(token), csrf_token())


# ---------- Redirecciones seguras ----------
def es_ruta_local(url):
    """Solo rutas relativas al sitio: empiezan por '/' pero no por '//' (ni '/\\')."""
    return isinstance(url, str) and url.startswith("/") and not url.startswith(("//", "/\\"))


def destino_seguro(*candidatos, defecto):
    """Primer candidato que sea una ruta local; si no, el destino por defecto."""
    for c in candidatos:
        if es_ruta_local(c):
            return c
    return defecto


def volver(defecto_endpoint, **kw):
    """Redirige a `next` (formulario) o al referrer, solo si son rutas locales."""
    return redirect(destino_seguro(request.form.get("next"), request.args.get("next"), request.referrer,
                                   defecto=url_for(defecto_endpoint, **kw)))


# ---------- Reloj de negocio (zona horaria configurable, por defecto America/Bogota) ----------
def zona_horaria():
    nombre = current_app.config.get("TZ") if has_app_context() else None
    if not nombre:
        from config import Config
        nombre = Config.TZ
    return ZoneInfo(nombre)


def _utcnow():
    """Único punto de lectura del reloj del sistema (las pruebas lo congelan)."""
    return datetime.now(timezone.utc)


def ahora():
    """Fecha y hora actual en la zona del negocio, sin tzinfo (comparable con los datos de la BD)."""
    return _utcnow().astimezone(zona_horaria()).replace(tzinfo=None, microsecond=0)


def hoy():
    return ahora().date()


# ---------- Fechas ----------
def parse_fecha(s):
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_hora(s):
    """Devuelve 'HH:MM:00' o None."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", (s or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}:00"


def fecha_es(s):
    d = parse_fecha(s) if isinstance(s, str) else s
    if not d:
        return s
    return f"{DIAS[d.weekday()][:3]} {d.strftime('%d/%m/%Y')}"


# ---------- Paginación ----------
class Pagina:
    def __init__(self, total, page, per_page):
        self.total, self.per_page = total, per_page
        self.pages = max(1, math.ceil(total / per_page)) if per_page else 1
        self.page = min(max(1, page), self.pages)
        self.offset = (self.page - 1) * per_page

    @property
    def tiene_anterior(self):
        return self.page > 1

    @property
    def tiene_siguiente(self):
        return self.page < self.pages

    def url(self, page):
        args = request.args.to_dict()
        args.pop("partial", None)
        args["page"] = page
        return url_for(request.endpoint, **(request.view_args or {}), **args)


def pagina_actual(total):
    p = request.args.get("page", "1")
    return Pagina(total, int(p) if p.isdigit() else 1, current_app.config.get("PAGE_SIZE", 20))
