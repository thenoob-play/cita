from werkzeug.security import generate_password_hash

from ..db import get_db

COLS = """u.id, u.nombre, u.documento, u.telefono, u.correo, u.rol, u.activo,
          u.especialidad_id, u.created_at, u.ultimo_acceso, e.nombre AS especialidad"""
FROM = "FROM usuarios u LEFT JOIN especialidades e ON e.id = u.especialidad_id"


def hash_password(pw):
    return generate_password_hash(pw, method="pbkdf2:sha256")


def get(uid):
    return get_db().one(f"SELECT {COLS}, u.password_hash {FROM} WHERE u.id = %s", (uid,))


def por_correo(correo):
    return get_db().one(f"SELECT {COLS}, u.password_hash {FROM} WHERE u.correo = %s", (correo,))


def _where(rol, q, solo_activos):
    sql, p = " WHERE 1=1", []
    if rol:
        sql += " AND u.rol = %s"
        p.append(rol)
    if solo_activos:
        sql += " AND u.activo = 1"
    if q:
        sql += " AND (u.nombre LIKE %s OR u.documento LIKE %s OR u.correo LIKE %s)"
        p += [f"%{q}%"] * 3
    return sql, p


def listar(rol=None, q=None, solo_activos=False, limite=None, offset=0):
    w, p = _where(rol, q, solo_activos)
    sql = f"SELECT {COLS} {FROM}{w} ORDER BY u.nombre, u.id"
    if limite:
        sql += f" LIMIT {int(limite)} OFFSET {int(offset)}"
    return get_db().all(sql, p)


def contar_filtrado(rol=None, q=None, solo_activos=False):
    w, p = _where(rol, q, solo_activos)
    return get_db().one(f"SELECT COUNT(*) AS n {FROM}{w}", p)["n"]


def duplicados(documento, correo, excluir_id=None):
    """Lista de campos ya usados por otro usuario."""
    sql = "SELECT documento, correo FROM usuarios WHERE (documento = %s OR correo = %s)"
    p = [documento, correo]
    if excluir_id:
        sql += " AND id <> %s"
        p.append(excluir_id)
    msgs = []
    for r in get_db().all(sql, p):
        if r["documento"] == documento and "El documento ya está registrado." not in msgs:
            msgs.append("El documento ya está registrado.")
        if r["correo"] == correo and "El correo ya está registrado." not in msgs:
            msgs.append("El correo ya está registrado.")
    return msgs


def crear(d):
    return get_db().execute(
        """INSERT INTO usuarios (nombre, documento, telefono, correo, password_hash, rol, especialidad_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (d["nombre"], d["documento"], d["telefono"] or None, d["correo"],
         hash_password(d["password"]), d["rol"], d.get("especialidad_id")))


def actualizar(uid, d):
    db = get_db()
    with db.transaction():
        db.execute(
            """UPDATE usuarios SET nombre=%s, documento=%s, telefono=%s, correo=%s, especialidad_id=%s
               WHERE id=%s""",
            (d["nombre"], d["documento"], d["telefono"] or None, d["correo"], d.get("especialidad_id"), uid))
        if d.get("password"):
            set_password(uid, d["password"])


def set_password(uid, password):
    get_db().execute("UPDATE usuarios SET password_hash=%s WHERE id=%s", (hash_password(password), uid))


def cambiar_rol(uid, rol):
    get_db().execute("UPDATE usuarios SET rol=%s WHERE id=%s", (rol, uid))


def set_activo(uid, activo):
    get_db().execute("UPDATE usuarios SET activo=%s WHERE id=%s", (1 if activo else 0, uid))


def tiene_citas(uid):
    r = get_db().one("SELECT COUNT(*) AS n FROM citas WHERE paciente_id=%s OR profesional_id=%s", (uid, uid))
    return r["n"] > 0


def eliminar(uid):
    get_db().execute("DELETE FROM usuarios WHERE id=%s", (uid,))


def contar(rol):
    return get_db().one("SELECT COUNT(*) AS n FROM usuarios WHERE rol=%s", (rol,))["n"]


def registrar_acceso(uid, momento):
    get_db().execute("UPDATE usuarios SET ultimo_acceso=%s WHERE id=%s", (momento, uid))
