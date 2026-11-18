"""Horario semanal recurrente con vigencia.

Un registro nunca se edita: cambiar un bloque = cerrarlo (vigente_hasta = día anterior) y crear
otro; eliminar = cerrarlo. vigente_desde/vigente_hasta NULL significan "sin límite".
Un bloque con vigente_hasta < vigente_desde nunca estuvo vigente (se cerró antes de empezar).
"""
from ..db import get_db

COLS = "id, profesional_id, dia_semana, hora_inicio, hora_fin, vigente_desde, vigente_hasta"
NO_MUERTO = "(vigente_desde IS NULL OR vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)"


def listar(prof_id, desde_iso=None, historial=False):
    """Bloques vigentes o futuros a partir de `desde_iso` (o todos si historial=True)."""
    sql, p = f"SELECT {COLS} FROM horarios WHERE profesional_id=%s", [prof_id]
    if not historial:
        sql += f" AND {NO_MUERTO} AND (vigente_hasta IS NULL OR vigente_hasta >= %s)"
        p.append(desde_iso)
    return get_db().all(sql + " ORDER BY dia_semana, hora_inicio, vigente_desde", p)


def get(hid, prof_id):
    return get_db().one(f"SELECT {COLS} FROM horarios WHERE id=%s AND profesional_id=%s", (hid, prof_id))


def vigentes_en(prof_id, fecha):
    """Bloques semanales del día de la semana de `fecha` vigentes en esa fecha."""
    iso = fecha.isoformat()
    return get_db().all(
        f"""SELECT {COLS} FROM horarios
            WHERE profesional_id=%s AND dia_semana=%s
              AND (vigente_desde IS NULL OR vigente_desde <= %s)
              AND (vigente_hasta IS NULL OR vigente_hasta >= %s)
            ORDER BY hora_inicio""", (prof_id, fecha.weekday(), iso, iso))


def solapa(prof_id, dia, ini, fin, desde_iso, hasta_iso=None):
    """¿Algún bloque del mismo día se cruza en horas Y en vigencia con el propuesto?"""
    sql = f"""SELECT COUNT(*) AS n FROM horarios
              WHERE profesional_id=%s AND dia_semana=%s AND hora_inicio < %s AND hora_fin > %s AND {NO_MUERTO}
                AND (vigente_hasta IS NULL OR vigente_hasta >= %s)"""
    p = [prof_id, dia, fin, ini, desde_iso]
    if hasta_iso:
        sql += " AND (vigente_desde IS NULL OR vigente_desde <= %s)"
        p.append(hasta_iso)
    return get_db().one(sql, p)["n"] > 0


def agregar(prof_id, dia, ini, fin, desde_iso, hasta_iso=None):
    return get_db().execute(
        """INSERT INTO horarios (profesional_id, dia_semana, hora_inicio, hora_fin, vigente_desde, vigente_hasta)
           VALUES (%s,%s,%s,%s,%s,%s)""", (prof_id, dia, ini, fin, desde_iso, hasta_iso))


def cerrar(hid, prof_id, hasta_iso):
    get_db().execute("UPDATE horarios SET vigente_hasta=%s WHERE id=%s AND profesional_id=%s",
                     (hasta_iso, hid, prof_id))
