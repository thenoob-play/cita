from datetime import datetime

from ..db import IntegrityError, get_db
from ..services import agenda
from ..utils import ESTADOS, ahora, fecha_es, parse_fecha, parse_hora
from . import usuario

BASE = """
    SELECT c.id, c.paciente_id, c.profesional_id, c.fecha, c.hora, c.estado, c.motivo, c.created_at,
           c.requiere_reprogramacion,
           p.nombre AS paciente_nombre, p.documento AS paciente_documento,
           p.telefono AS paciente_telefono, p.correo AS paciente_correo,
           pr.nombre AS profesional_nombre, e.nombre AS especialidad
    FROM citas c
    JOIN usuarios p  ON p.id  = c.paciente_id
    JOIN usuarios pr ON pr.id = c.profesional_id
    LEFT JOIN especialidades e ON e.id = pr.especialidad_id
"""
FROM_JOIN = """FROM citas c JOIN usuarios p ON p.id = c.paciente_id
               JOIN usuarios pr ON pr.id = c.profesional_id"""

MSG_CONCURRENCIA = ("Ese horario acaba de ser reservado por otra persona (o el paciente ya tiene una cita a esa hora). "
                    "Elija otra hora.")


def _where(f):
    sql, p = " WHERE 1=1", []
    if f.get("q"):
        sql += " AND (p.nombre LIKE %s OR p.documento LIKE %s OR pr.nombre LIKE %s OR c.motivo LIKE %s)"
        p += [f"%{f['q']}%"] * 4
    if f.get("estado") in ESTADOS:
        sql += " AND c.estado = %s"
        p.append(f["estado"])
    if f.get("profesional_id"):
        sql += " AND c.profesional_id = %s"
        p.append(f["profesional_id"])
    if f.get("paciente_id"):
        sql += " AND c.paciente_id = %s"
        p.append(f["paciente_id"])
    if f.get("desde"):
        sql += " AND c.fecha >= %s"
        p.append(f["desde"])
    if f.get("hasta"):
        sql += " AND c.fecha <= %s"
        p.append(f["hasta"])
    if f.get("reprogramar"):
        sql += " AND c.requiere_reprogramacion = 1 AND c.estado = 'Pendiente'"
    return sql, p


def buscar(filtros, limite=500, asc=False, offset=0):
    w, p = _where(filtros)
    orden = "ASC" if asc else "DESC"
    return get_db().all(f"{BASE}{w} ORDER BY c.fecha {orden}, c.hora {orden}, c.id {orden} "
                        f"LIMIT {int(limite)} OFFSET {int(offset)}", p)


def contar(filtros):
    w, p = _where(filtros)
    return get_db().one(f"SELECT COUNT(*) AS n {FROM_JOIN}{w}", p)["n"]


def get(cid):
    return get_db().one(f"{BASE} WHERE c.id = %s", (cid,))


def conteo_por_estado(filtros):
    w, p = _where(filtros)
    rows = get_db().all(f"SELECT c.estado, COUNT(*) AS total {FROM_JOIN}{w} GROUP BY c.estado", p)
    d = {e: 0 for e in ESTADOS}
    d.update({r["estado"]: r["total"] for r in rows})
    return d


def conteo_por_profesional(filtros):
    w, p = _where(filtros)
    return get_db().all(
        f"SELECT pr.id, pr.nombre, COUNT(*) AS total {FROM_JOIN}{w} GROUP BY pr.id, pr.nombre ORDER BY total DESC", p)


# ---------- CRUD ----------
class _Rechazo(Exception):
    pass


def programar(paciente_id, profesional_id, fecha_s, hora_s, motivo=None, cita_id=None):
    """Crea (cita_id=None) o reprograma/actualiza una cita de forma atómica.

    La validación de horario y de cruces se hace DENTRO de la transacción, con la agenda del
    profesional y del paciente bloqueada; los índices únicos de la BD son la última barrera.
    Si `motivo` es None al actualizar, solo cambian fecha y hora (reprogramación del paciente).
    Devuelve (cita_id, error).
    """
    db = get_db()
    try:
        with db.transaction():
            db.lock_profesional(*(x for x in (profesional_id, paciente_id) if str(x or "").isdigit()))
            fecha, hms, error = validar_programacion(paciente_id, profesional_id, fecha_s, hora_s, excluir_id=cita_id)
            if error:
                raise _Rechazo(error)
            if cita_id is None:
                cita_id = db.execute(
                    """INSERT INTO citas (paciente_id, profesional_id, fecha, hora, estado, motivo)
                       VALUES (%s,%s,%s,%s,'Pendiente',%s)""",
                    (int(paciente_id), int(profesional_id), fecha, hms, motivo or "Consulta general"))
            elif motivo is None:      # reagendar limpia la marca de reprogramación
                db.execute("UPDATE citas SET fecha=%s, hora=%s, estado='Pendiente', requiere_reprogramacion=0 "
                           "WHERE id=%s", (fecha, hms, cita_id))
            else:
                db.execute("UPDATE citas SET paciente_id=%s, profesional_id=%s, fecha=%s, hora=%s, motivo=%s, "
                           "requiere_reprogramacion=0 WHERE id=%s",
                           (int(paciente_id), int(profesional_id), fecha, hms, motivo, cita_id))
        return cita_id, None
    except _Rechazo as exc:
        return None, str(exc)
    except IntegrityError:
        return None, MSG_CONCURRENCIA


def cambiar_estado(cid, estado):
    """Lanza IntegrityError si reactivar la cita choca con otra activa en el mismo horario."""
    get_db().execute("UPDATE citas SET estado=%s WHERE id=%s", (estado, cid))


def eliminar(cid):
    get_db().execute("DELETE FROM citas WHERE id=%s", (cid,))


# ---------- Disponibilidad (delegada en services.agenda) ----------
def slots_del_horario(prof_id, fecha):
    """Horas ofrecidas ese día según los bloques efectivos (semanal vigente - bloqueos + extras)."""
    return agenda.slots(prof_id, fecha)


def slots_disponibles(prof_id, fecha, excluir_id=None, paciente_id=None):
    slots = slots_del_horario(prof_id, fecha)
    if not slots:
        return []
    iso = fecha.isoformat()
    sql = "SELECT hora FROM citas WHERE fecha=%s AND estado <> 'Cancelada' AND (profesional_id=%s"
    p = [iso, prof_id]
    if paciente_id:
        sql += " OR paciente_id=%s"
        p.append(paciente_id)
    sql += ")"
    if excluir_id:
        sql += " AND id <> %s"
        p.append(excluir_id)
    ocupadas = {r["hora"] for r in get_db().all(sql, p)}
    momento = ahora()
    return [s for s in slots
            if s not in ocupadas and datetime.combine(fecha, datetime.strptime(s, "%H:%M").time()) > momento]


def cruce(prof_id, paciente_id, fecha_iso, hora_hms, excluir_id=None):
    """Devuelve 'profesional', 'paciente' o None."""
    base = "SELECT COUNT(*) AS n FROM citas WHERE fecha=%s AND hora=%s AND estado <> 'Cancelada' AND {} = %s"
    extra, ex = "", []
    if excluir_id:
        extra, ex = " AND id <> %s", [excluir_id]
    db = get_db()
    if db.one(base.format("profesional_id") + extra, [fecha_iso, hora_hms, prof_id] + ex)["n"]:
        return "profesional"
    if db.one(base.format("paciente_id") + extra, [fecha_iso, hora_hms, paciente_id] + ex)["n"]:
        return "paciente"
    return None


def validar_programacion(paciente_id, profesional_id, fecha_s, hora_s, excluir_id=None):
    """Valida fecha/hora/profesional/paciente. Devuelve (fecha_iso, hora_hms, error)."""
    prof = usuario.get(profesional_id) if str(profesional_id).isdigit() else None
    if not prof or prof["rol"] != "profesional" or not prof["activo"]:
        return None, None, "Seleccione un profesional válido y activo."
    pac = usuario.get(paciente_id) if str(paciente_id).isdigit() else None
    if not pac or pac["rol"] != "paciente" or not pac["activo"]:
        return None, None, "Seleccione un paciente válido y activo."
    fecha, hms = parse_fecha(fecha_s), parse_hora(hora_s)
    if not fecha or not hms:
        return None, None, "Fecha u hora con formato inválido."
    if datetime.combine(fecha, datetime.strptime(hms, "%H:%M:%S").time()) <= ahora():
        return None, None, "La cita debe programarse en una fecha y hora futuras."
    if hms[:5] not in slots_del_horario(prof["id"], fecha):
        return None, None, (f"{prof['nombre']} no atiende el {fecha_es(fecha)} a las {hms[:5]} "
                            f"(consulte su horario de atención).")
    quien = cruce(prof["id"], pac["id"], fecha.isoformat(), hms, excluir_id)
    if quien == "profesional":
        return None, None, "El profesional ya tiene una cita asignada en esa fecha y hora."
    if quien == "paciente":
        return None, None, "El paciente ya tiene otra cita programada en ese mismo horario."
    return fecha.isoformat(), hms, None


def proximas_del_paciente(paciente_id):
    return buscar({"paciente_id": paciente_id}, limite=100)


def profesional_atiende_a(prof_id, paciente_id):
    r = get_db().one("SELECT COUNT(*) AS n FROM citas WHERE profesional_id=%s AND paciente_id=%s",
                     (prof_id, paciente_id))
    return r["n"] > 0


def pacientes_de_profesional(prof_id, q=None):
    sql = """SELECT DISTINCT p.id, p.nombre, p.documento, p.telefono, p.correo
             FROM citas c JOIN usuarios p ON p.id = c.paciente_id WHERE c.profesional_id = %s"""
    prm = [prof_id]
    if q:
        sql += " AND (p.nombre LIKE %s OR p.documento LIKE %s)"
        prm += [f"%{q}%"] * 2
    return get_db().all(sql + " ORDER BY p.nombre", prm)
