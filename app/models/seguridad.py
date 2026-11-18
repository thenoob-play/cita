"""Límite de intentos de inicio de sesión y tokens de recuperación de contraseña."""
import hashlib
import secrets
from datetime import timedelta

from flask import current_app

from ..db import get_db
from ..utils import ahora

FMT = "%Y-%m-%d %H:%M:%S"


# ---------------- Intentos fallidos (por correo + IP) ----------------
def bloqueado(correo, ip):
    cfg = current_app.config
    desde = (ahora() - timedelta(minutes=cfg["LOGIN_VENTANA_MIN"])).strftime(FMT)
    n = get_db().one("SELECT COUNT(*) AS n FROM intentos_login WHERE correo=%s AND ip=%s AND momento >= %s",
                     (correo, ip, desde))["n"]
    return n >= cfg["LOGIN_MAX_INTENTOS"]


def registrar_fallo(correo, ip):
    db = get_db()
    db.execute("INSERT INTO intentos_login (correo, ip, momento) VALUES (%s,%s,%s)",
               (correo[:100], ip[:45], ahora().strftime(FMT)))
    db.execute("DELETE FROM intentos_login WHERE momento < %s", ((ahora() - timedelta(days=1)).strftime(FMT),))


def limpiar_intentos(correo, ip=None):
    if ip is None:
        get_db().execute("DELETE FROM intentos_login WHERE correo=%s", (correo,))
    else:
        get_db().execute("DELETE FROM intentos_login WHERE correo=%s AND ip=%s", (correo, ip))


# ---------------- Tokens de recuperación (un solo uso, expiran) ----------------
def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def crear_token(usuario_id):
    """Invalida los tokens anteriores del usuario y devuelve uno nuevo (en claro: solo viaja por correo)."""
    token = secrets.token_urlsafe(32)
    expira = (ahora() + timedelta(minutes=current_app.config["RESET_TOKEN_MIN"])).strftime(FMT)
    db = get_db()
    with db.transaction():
        db.execute("UPDATE tokens_recuperacion SET usado=1 WHERE usuario_id=%s AND usado=0", (usuario_id,))
        db.execute("INSERT INTO tokens_recuperacion (usuario_id, token_hash, expira_en) VALUES (%s,%s,%s)",
                   (usuario_id, _hash(token), expira))
    return token


def token_vigente(token):
    """Fila del token si existe, no se ha usado y no ha expirado; si no, None."""
    if not token or len(token) > 200:
        return None
    return get_db().one(
        "SELECT id, usuario_id FROM tokens_recuperacion WHERE token_hash=%s AND usado=0 AND expira_en > %s",
        (_hash(token), ahora().strftime(FMT)))


def consumir_token(token_id):
    """Marca el token como usado. False si otra petición lo consumió primero."""
    return get_db().rowcount("UPDATE tokens_recuperacion SET usado=1 WHERE id=%s AND usado=0", (token_id,)) == 1
