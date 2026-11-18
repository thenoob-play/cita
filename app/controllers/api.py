"""Endpoints JSON consumidos por JavaScript (Fetch API)."""
from flask import Blueprint, jsonify, request, session

from ..models import cita, excepcion
from ..utils import DIAS, fecha_es, parse_fecha, role_required

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/disponibilidad")
@role_required()
def disponibilidad():
    """Horas libres de un profesional en una fecha (bloques efectivos de services.agenda, citas y cruces del paciente)."""
    prof = request.args.get("profesional_id", "")
    fecha = parse_fecha(request.args.get("fecha"))
    if not prof.isdigit() or not fecha:
        return jsonify(slots=[], mensaje="Seleccione profesional y fecha.")
    paciente_id = session["user_id"] if session.get("rol") == "paciente" else request.args.get("paciente_id")
    paciente_id = int(paciente_id) if str(paciente_id or "").isdigit() else None
    excluir = request.args.get("excluir_cita")
    excluir = int(excluir) if excluir and excluir.isdigit() else None
    slots = cita.slots_disponibles(int(prof), fecha, excluir, paciente_id)
    if slots:
        msg = f"{len(slots)} horario(s) disponible(s) el {DIAS[fecha.weekday()]}."
    elif cita.slots_del_horario(int(prof), fecha):
        msg = "No quedan horarios libres en esa fecha."
    elif any(e["tipo"] == "bloqueo" for e in excepcion.del_dia(int(prof), fecha)):
        msg = f"El profesional no atiende el {fecha_es(fecha)} (agenda bloqueada ese día)."
    else:
        msg = f"El profesional no atiende los {DIAS[fecha.weekday()].lower()}."
    return jsonify(slots=slots, mensaje=msg)
