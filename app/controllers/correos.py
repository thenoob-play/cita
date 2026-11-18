"""Vista previa de correos (modo demostración) y avisos de envío sin datos sensibles en flash.

Los mensajes flash viajan en la cookie de sesión (legible en el navegador): por eso nunca
llevan el cuerpo del correo; solo un enlace a esta vista previa, protegida por rol.
"""
from flask import Blueprint, abort, flash, render_template, session, url_for
from markupsafe import Markup, escape

from ..models import recordatorio
from ..utils import role_required

bp = Blueprint("correos", __name__, url_prefix="/correos")


@bp.route("/<int:rid>")
@role_required("administrador", "recepcionista", "paciente")
def vista_previa(rid):
    r = recordatorio.get(rid) or abort(404)
    if session.get("rol") == "paciente" and r["paciente_id"] != session["user_id"]:
        abort(404)
    resp = render_template("correos/vista_previa.html", r=r)
    return resp, 200, {"Cache-Control": "no-store"}


def avisar(r, mostrar_destino=True):
    """Mensaje flash según el resultado de recordatorio.enviar_para_cita()."""
    destino = f" a {r['correo']}" if mostrar_destino and r.get("correo") else ""
    if r["modo"] == "smtp":
        flash(f"Correo enviado{destino}.", "success")
    elif r["modo"] == "pendiente":
        flash(f"Correo en cola de envío{destino}.", "info")
    elif r["modo"] == "demo":
        enlace = url_for("correos.vista_previa", rid=r["id"])
        flash(Markup("[MODO DEMOSTRACIÓN] El correo no se envió (SMTP no configurado) y quedó registrado. "
                     f'<a href="{escape(enlace)}" class="alert-link">Ver vista previa</a>'), "info")
    else:
        flash("No se pudo enviar el correo (revise la configuración SMTP). Quedó registrado en el sistema.",
              "warning")
