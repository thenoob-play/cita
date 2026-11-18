"""Historia clínica INMUTABLE.

* Una nota nunca se modifica ni se borra.
* Corregir = insertar una nota nueva con `corrige_a` = id de la nota corregida.
* Eliminar = anular (anulada=1 + motivo_anulacion); la nota sigue existiendo.
"""
from ..db import get_db
from ..utils import ahora

COLS = """h.id, h.cita_id, h.observacion, h.registrado_por, h.fecha_registro, h.corrige_a,
          h.anulada, h.motivo_anulacion"""


def por_paciente(paciente_id):
    """Todas las notas del paciente; `vigente` = no anulada y no reemplazada por una corrección."""
    notas = get_db().all(f"""
        SELECT {COLS}, u.nombre AS medico_nombre, c.fecha AS cita_fecha, c.motivo AS cita_motivo
        FROM historial_citas h
        JOIN citas c ON c.id = h.cita_id
        JOIN usuarios u ON u.id = h.registrado_por
        WHERE c.paciente_id = %s
        ORDER BY h.fecha_registro DESC, h.id DESC""", (paciente_id,))
    corregidas = {n["corrige_a"] for n in notas if n["corrige_a"]}
    for n in notas:
        n["corregida"] = n["id"] in corregidas
        n["vigente"] = not n["anulada"] and not n["corregida"]
    return notas


def get(hid):
    return get_db().one(f"SELECT {COLS} FROM historial_citas h WHERE h.id=%s", (hid,))


def fue_corregida(hid):
    return get_db().one("SELECT COUNT(*) AS n FROM historial_citas WHERE corrige_a=%s", (hid,))["n"] > 0


def crear(cita_id, observacion, medico_id, corrige_a=None):
    return get_db().execute(
        """INSERT INTO historial_citas (cita_id, observacion, registrado_por, corrige_a, fecha_registro)
           VALUES (%s,%s,%s,%s,%s)""",
        (cita_id, observacion, medico_id, corrige_a, ahora().strftime("%Y-%m-%d %H:%M:%S")))


def anular(hid, motivo):
    """Devuelve True si la nota quedó anulada (False si ya lo estaba)."""
    return get_db().rowcount(
        "UPDATE historial_citas SET anulada=1, motivo_anulacion=%s WHERE id=%s AND anulada=0", (motivo, hid)) == 1


def notas_de_cita(cita_id):
    return get_db().one("SELECT COUNT(*) AS n FROM historial_citas WHERE cita_id=%s", (cita_id,))["n"]
