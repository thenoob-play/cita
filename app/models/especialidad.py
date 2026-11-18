from ..db import get_db


def listar():
    return get_db().all("""
        SELECT e.id, e.nombre, COUNT(u.id) AS profesionales
        FROM especialidades e LEFT JOIN usuarios u ON u.especialidad_id = e.id
        GROUP BY e.id, e.nombre ORDER BY e.nombre""")


def get(eid):
    return get_db().one("SELECT * FROM especialidades WHERE id = %s", (eid,))


def crear(nombre):
    return get_db().execute("INSERT INTO especialidades (nombre) VALUES (%s)", (nombre,))


def renombrar(eid, nombre):
    get_db().execute("UPDATE especialidades SET nombre = %s WHERE id = %s", (nombre, eid))


def eliminar(eid):
    get_db().execute("DELETE FROM especialidades WHERE id = %s", (eid,))
