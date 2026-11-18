"""Registro de auditoría: quién hizo qué, sobre qué entidad y cuándo.

Nunca guarde contenido clínico en `detalle`: solo identificadores, estados y motivos.
"""
import json

from flask import has_request_context, session

from ..db import get_db
from ..utils import ahora


def registrar(accion, entidad, entidad_id=None, detalle=None, override=False, usuario_id=None):
    if usuario_id is None and has_request_context():
        usuario_id = session.get("user_id")
    if detalle is not None and not isinstance(detalle, str):
        detalle = json.dumps(detalle, ensure_ascii=False, default=str)
    get_db().execute(
        """INSERT INTO auditoria (usuario_id, accion, entidad, entidad_id, detalle, override, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (usuario_id, accion, entidad, entidad_id, detalle, 1 if override else 0,
         ahora().strftime("%Y-%m-%d %H:%M:%S")))


def listar(entidad=None, entidad_id=None, limite=100):
    sql, p = """SELECT a.*, u.nombre AS usuario_nombre FROM auditoria a
                LEFT JOIN usuarios u ON u.id = a.usuario_id WHERE 1=1""", []
    if entidad:
        sql += " AND a.entidad = %s"
        p.append(entidad)
    if entidad_id is not None:
        sql += " AND a.entidad_id = %s"
        p.append(entidad_id)
    return get_db().all(sql + f" ORDER BY a.id DESC LIMIT {int(limite)}", p)


ACCIONES = {
    "crear": "Creó", "editar": "Editó", "eliminar": "Eliminó", "reprogramar": "Reprogramó",
    "cambiar_estado": "Cambió el estado de", "activar": "Activó", "desactivar": "Desactivó",
    "crear_nota": "Registró una nota en", "corregir_nota": "Corrigió una nota en", "anular_nota": "Anuló una nota en",
    "leer_historial": "Consultó el historial de", "forzar_atencion": "Forzó la atención de",
    "cerrar": "Cerró", "solicitar_recuperacion": "Solicitó recuperar la contraseña de",
    "restablecer_password": "Restableció la contraseña de", "cambiar_password": "Cambió la contraseña de",
    "iniciar_sesion": "Inició sesión en", "exportar_datos": "Descargó los datos de",
}


def de_usuario(uid, limite=15):
    """Actividad reciente hecha por un usuario (para la página Mi cuenta)."""
    rows = get_db().all(f"SELECT id, accion, entidad, entidad_id, created_at FROM auditoria WHERE usuario_id=%s "
                        f"ORDER BY id DESC LIMIT {int(limite)}", (uid,))
    for r in rows:
        r["texto"] = f"{ACCIONES.get(r['accion'], r['accion'].replace('_', ' ').capitalize())} {r['entidad'].replace('_', ' ')}"
        if r["entidad_id"]:
            r["texto"] += f" #{r['entidad_id']}"
    return rows
