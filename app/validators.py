"""Validaciones del lado del servidor (formularios de personas)."""
import re

from .utils import clean

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def validar_persona(form, rol, *, password_obligatoria=True, telefono_obligatorio=False):
    """Devuelve (datos, errores) para crear/editar un usuario."""
    errores = []
    d = {
        "nombre": clean(form.get("nombre")),
        "documento": clean(form.get("documento")),
        "telefono": clean(form.get("telefono")),
        "correo": clean(form.get("correo")).lower(),
        "password": form.get("password", ""),
        "rol": rol,
        "especialidad_id": None,
    }
    if len(d["nombre"]) < 3 or len(d["nombre"]) > 100:
        errores.append("El nombre debe tener entre 3 y 100 caracteres.")
    if not re.fullmatch(r"\d{5,15}", d["documento"]):
        errores.append("El documento debe tener entre 5 y 15 dígitos.")
    if d["telefono"] or telefono_obligatorio:
        if not re.fullmatch(r"\d{7,15}", d["telefono"]):
            errores.append("El teléfono debe tener entre 7 y 15 dígitos.")
    if not EMAIL_RE.match(d["correo"]) or len(d["correo"]) > 100:
        errores.append("El correo electrónico no es válido.")
    if d["password"] or password_obligatoria:
        if len(d["password"]) < 6:
            errores.append("La contraseña debe tener al menos 6 caracteres.")
        p2 = form.get("password2")
        if p2 is not None and p2 != d["password"]:
            errores.append("Las contraseñas no coinciden.")
    if rol == "profesional":
        esp = clean(form.get("especialidad_id"))
        if esp.isdigit():
            d["especialidad_id"] = int(esp)
        else:
            errores.append("Seleccione una especialidad.")
    return d, errores
