"""Excepciones de horario por fecha: 'bloqueo' (sin horas = día completo) y 'extra' (turno adicional)."""
from ..db import get_db

COLS = "e.id, e.profesional_id, e.fecha, e.tipo, e.hora_inicio, e.hora_fin, e.motivo, e.creado_por, e.created_at"


def del_dia(prof_id, fecha):
    return get_db().all(f"SELECT {COLS} FROM excepciones_horario e WHERE e.profesional_id=%s AND e.fecha=%s "
                        "ORDER BY e.tipo, e.hora_inicio", (prof_id, fecha.isoformat()))


def listar(prof_id, desde_iso):
    return get_db().all(
        f"""SELECT {COLS}, u.nombre AS creado_por_nombre FROM excepciones_horario e
            LEFT JOIN usuarios u ON u.id = e.creado_por
            WHERE e.profesional_id=%s AND e.fecha >= %s ORDER BY e.fecha, e.hora_inicio""", (prof_id, desde_iso))


def get(eid, prof_id):
    return get_db().one(f"SELECT {COLS} FROM excepciones_horario e WHERE e.id=%s AND e.profesional_id=%s",
                        (eid, prof_id))


def solapa(prof_id, fecha_iso, tipo, ini, fin):
    """¿Ya hay una excepción del mismo tipo ese día que se cruce? (día completo cruza con todo)."""
    filas = get_db().all("SELECT hora_inicio, hora_fin FROM excepciones_horario WHERE profesional_id=%s "
                         "AND fecha=%s AND tipo=%s", (prof_id, fecha_iso, tipo))
    for f in filas:
        if f["hora_inicio"] is None or ini is None:
            return True
        if f["hora_inicio"] < fin[:5] and f["hora_fin"] > ini[:5]:
            return True
    return False


def agregar(prof_id, fecha_iso, tipo, ini, fin, motivo, creado_por):
    return get_db().execute(
        """INSERT INTO excepciones_horario (profesional_id, fecha, tipo, hora_inicio, hora_fin, motivo, creado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""", (prof_id, fecha_iso, tipo, ini, fin, motivo, creado_por))


def eliminar(eid, prof_id):
    get_db().execute("DELETE FROM excepciones_horario WHERE id=%s AND profesional_id=%s", (eid, prof_id))
