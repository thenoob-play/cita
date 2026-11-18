"""Servicio ÚNICO de agenda: toda la lógica de disponibilidad y de atención pasa por aquí.

bloques_efectivos(profesional_id, fecha):
    1. bloques semanales vigentes en esa fecha (horarios.vigente_desde/vigente_hasta)
    2. menos los bloqueos de ese día (un bloqueo sin horas cubre el día completo)
    3. más los turnos extra de ese día
Los bloques se devuelven como [(inicio_min, fin_min)] ordenados y fusionados.

Lo usan: slots (agendar / /api/disponibilidad / reprogramar), la agenda del profesional,
puede_atender (regla de atención) y el análisis de impacto de cambios de horario.
"""
from datetime import datetime, timedelta

from flask import current_app

from ..db import get_db
from ..models import auditoria, excepcion, horario
from ..utils import ahora, fecha_es, hoy, parse_fecha

ESTADOS_ATENCION = ("Pendiente", "Atendida", "Inasistida")


def a_minutos(hhmm):
    h, m = str(hhmm)[:5].split(":")
    return int(h) * 60 + int(m)


def a_hora(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def duracion_cita(profesional_id=None):
    """Duración de una cita en minutos.
    PUNTO DE EXTENSIÓN: hoy es SLOT_MINUTES para todos; aquí se puede resolver la duración por
    especialidad del profesional (p. ej. una tabla especialidades.duracion_min) sin tocar a los llamadores."""
    return current_app.config["SLOT_MINUTES"]


# ---------------- Álgebra de intervalos ----------------
def _fusionar(bloques):
    out = []
    for ini, fin in sorted(bloques):
        if out and ini <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], fin))
        else:
            out.append((ini, fin))
    return out


def _restar(bloques, ini, fin):
    out = []
    for a, b in bloques:
        if fin <= a or ini >= b:
            out.append((a, b))
            continue
        if a < ini:
            out.append((a, ini))
        if fin < b:
            out.append((fin, b))
    return out


# ---------------- Bloques efectivos ----------------
def bloques_efectivos(profesional_id, fecha):
    bloques = _fusionar([(a_minutos(h["hora_inicio"]), a_minutos(h["hora_fin"]))
                         for h in horario.vigentes_en(profesional_id, fecha)])
    excepciones = excepcion.del_dia(profesional_id, fecha)
    for e in excepciones:
        if e["tipo"] == "bloqueo":
            if e["hora_inicio"] is None:
                bloques = []
            else:
                bloques = _restar(bloques, a_minutos(e["hora_inicio"]), a_minutos(e["hora_fin"]))
    extras = [(a_minutos(e["hora_inicio"]), a_minutos(e["hora_fin"])) for e in excepciones if e["tipo"] == "extra"]
    return _fusionar(bloques + extras)


def franjas(profesional_id, fecha):
    """Bloques efectivos en texto: [('08:00', '12:00'), ...]."""
    return [(a_hora(a), a_hora(b)) for a, b in bloques_efectivos(profesional_id, fecha)]


def slots(profesional_id, fecha, bloques=None):
    """Horas de inicio ofrecidas ese día (cada cita debe terminar dentro de su bloque)."""
    dur = duracion_cita(profesional_id)
    out = []
    for ini, fin in (bloques if bloques is not None else bloques_efectivos(profesional_id, fecha)):
        t = ini
        while t + dur <= fin:
            out.append(a_hora(t))
            t += dur
    return out


def en_bloque(profesional_id, fecha, hora, bloques=None):
    """La cita empieza dentro de un bloque efectivo y termina antes o igual a su fin."""
    inicio = a_minutos(hora)
    fin = inicio + duracion_cita(profesional_id)
    for a, b in (bloques if bloques is not None else bloques_efectivos(profesional_id, fecha)):
        if a <= inicio < b and fin <= b:
            return True
    return False


# ---------------- Turno en tiempo real ----------------
def turno_en(profesional_id, momento=None, bloques=None):
    """Bloque efectivo de HOY que contiene la hora actual: ('HH:MM', 'HH:MM') o None.

    La entrada es inclusiva y la salida exclusiva: con salida 12:00 se atiende a las 11:59, no a las 12:00.
    Usa el reloj del negocio (utils.ahora(), zona TZ). Los bloques que cruzan medianoche no se admiten
    (admin los rechaza al guardarlos); si alguno llegara a la BD, inicio > fin y nunca contiene la hora,
    de modo que la regla falla cerrada (no permite atender).
    """
    momento = momento or ahora()
    if bloques is None:
        bloques = bloques_efectivos(profesional_id, momento.date())
    actual = momento.hour * 60 + momento.minute
    for a, b in bloques:
        if a <= actual < b:
            return a_hora(a), a_hora(b)
    return None


def _texto_franjas(bloques):
    partes = [f"{a_hora(a)}–{a_hora(b)}" for a, b in bloques]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def motivo_fuera_de_turno(momento, bloques):
    """Mensaje para el profesional cuando la hora actual no cae en ningún bloque de hoy."""
    if not bloques:
        return "Hoy no tiene horario de atención."
    actual = momento.hour * 60 + momento.minute
    if actual < bloques[0][0]:
        detalle = f"su turno empieza a las {a_hora(bloques[0][0])}"
    elif actual >= bloques[-1][1]:
        detalle = f"su turno de hoy terminó a las {a_hora(bloques[-1][1])}"
    else:
        siguiente = next(a for a, _ in bloques if a > actual)
        detalle = f"está en pausa; retoma a las {a_hora(siguiente)}"
    return (f"Fuera de su horario de atención (ahora son las {momento:%H:%M}; {detalle}). "
            f"Hoy atiende: {_texto_franjas(bloques)}.")


# ---------------- Regla de atención ----------------
def puede_atender(cita, profesional, momento=None, estado=None):
    """¿Puede `profesional` registrar la atención de `cita` en `momento`?

    Exige: es el profesional asignado · la cita cae dentro de un bloque efectivo de su fecha ·
    requiere_reprogramacion = 0 · la fecha de la cita es hoy (zona del negocio) · la hora actual está
    dentro de un turno efectivo de hoy (turno_en) · para Inasistida, han pasado
    TOLERANCIA_INASISTENCIA_MIN minutos desde la hora de la cita.
    Aplica a cambiar el estado y a escribir o corregir notas clínicas. El override del administrador
    (admin.atencion_forzada) no pasa por aquí a propósito: queda auditado con override=1.
    Devuelve (True, '') o (False, motivo legible).
    """
    momento = momento or ahora()
    if not profesional or not cita or cita["profesional_id"] != profesional["id"]:
        return False, "Solo el profesional asignado puede atender esta cita."
    if cita["estado"] == "Cancelada":
        return False, "La cita está cancelada."
    fecha = parse_fecha(cita["fecha"])
    bloques = bloques_efectivos(cita["profesional_id"], fecha)
    if not bloques:          # sin horario ese día o bloqueo de día completo
        return False, ("Hoy no tiene horario de atención." if fecha == momento.date()
                       else f"No tiene horario de atención el {fecha_es(fecha)}.")
    if not en_bloque(cita["profesional_id"], fecha, cita["hora"], bloques):
        return False, "La cita está fuera de la franja de atención de ese día."
    if cita.get("requiere_reprogramacion"):
        return False, "La cita requiere reprogramación por un cambio de horario: recepción debe reagendarla."
    if fecha != momento.date():
        return False, f"Solo se puede atender el día de la cita ({fecha_es(fecha)})."
    # fecha == hoy: los bloques de la cita son los de hoy
    if not turno_en(cita["profesional_id"], momento, bloques):
        return False, motivo_fuera_de_turno(momento, bloques)
    if estado == "Inasistida":
        tol = current_app.config["TOLERANCIA_INASISTENCIA_MIN"]
        desde = datetime.combine(fecha, datetime.strptime(cita["hora"][:5], "%H:%M").time()) + timedelta(minutes=tol)
        if momento < desde:
            return False, f"Podrá marcar Inasistida desde las {desde:%H:%M} ({tol} min de tolerancia)."
    return True, ""


def acciones_de_estado(cita, profesional, momento=None):
    """{estado: (habilitado, motivo)} para los botones de la agenda."""
    momento = momento or ahora()
    return {e: puede_atender(cita, profesional, momento, e) for e in ESTADOS_ATENCION if e != cita["estado"]}


# ---------------- Impacto de cambios de horario ----------------
def citas_fuera_de_bloque(profesional_id, desde=None):
    """Citas Pendiente (desde hoy) aún no marcadas que no caen dentro de los bloques efectivos."""
    desde = desde or hoy()
    citas = get_db().all(
        """SELECT c.id, c.fecha, c.hora, c.paciente_id, p.nombre AS paciente_nombre
           FROM citas c JOIN usuarios p ON p.id = c.paciente_id
           WHERE c.profesional_id=%s AND c.estado='Pendiente' AND c.requiere_reprogramacion=0 AND c.fecha >= %s
           ORDER BY c.fecha, c.hora""", (profesional_id, desde.isoformat()))
    cache, out = {}, []
    for c in citas:
        if c["fecha"] not in cache:
            cache[c["fecha"]] = bloques_efectivos(profesional_id, parse_fecha(c["fecha"]))
        if not en_bloque(profesional_id, None, c["hora"], cache[c["fecha"]]):
            out.append(c)
    return out


def marcar_reprogramacion(citas, motivo, detalle=None):
    db = get_db()
    for c in citas:
        db.execute("UPDATE citas SET requiere_reprogramacion=1 WHERE id=%s", (c["id"],))
        auditoria.registrar("marcar_reprogramacion", "cita", c["id"], {"motivo": motivo, **(detalle or {})})


class Rechazo(Exception):
    """El cambio no es válido (mensaje para el usuario)."""


class _Revertir(Exception):
    pass


def aplicar_cambio(profesional_id, cambio, confirmar=False, motivo="cambio de horario"):
    """Aplica `cambio()` en una transacción con la agenda del profesional bloqueada (SELECT ... FOR UPDATE).

    `cambio` valida (solapes incluidos) y escribe; lanza Rechazo si no procede. Después se calculan
    las citas Pendiente que quedarían fuera de bloque:
      * si hay y no se confirmó -> se revierte TODO y se devuelven para mostrarlas;
      * si se confirmó -> se marcan con requiere_reprogramacion = 1 y se auditan.
    Devuelve (estado, afectadas, error) con estado en {'ok', 'confirmar', 'error'}.
    """
    db = get_db()
    afectadas = []
    try:
        with db.transaction():
            db.lock_profesional(profesional_id)
            cambio()
            afectadas = citas_fuera_de_bloque(profesional_id)
            if afectadas and not confirmar:
                raise _Revertir()
            if afectadas:
                marcar_reprogramacion(afectadas, motivo)
        return "ok", afectadas, None
    except _Revertir:
        return "confirmar", afectadas, None
    except Rechazo as exc:
        return "error", [], str(exc)


def marcar_futuras_de_profesional(profesional_id, motivo):
    """B9: al desactivar a un profesional, todas sus citas Pendiente futuras requieren reprogramación."""
    citas = get_db().all("SELECT id FROM citas WHERE profesional_id=%s AND estado='Pendiente' "
                         "AND requiere_reprogramacion=0 AND fecha >= %s", (profesional_id, hoy().isoformat()))
    marcar_reprogramacion(citas, motivo)
    return len(citas)
