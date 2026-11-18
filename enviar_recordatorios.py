"""Envía los recordatorios de las citas pendientes de MAÑANA (y reintenta la cola pendiente).
Pensado para programarse una vez al día (Programador de tareas de Windows o cron):

    python enviar_recordatorios.py

Usa SMTP real si MAIL_SERVER está definido en .env; si no, queda en modo demostración.
Aquí el envío es síncrono: el script termina cuando se procesaron todos los correos.
"""
from app import create_app
from app.models import recordatorio

app = create_app()
with app.app_context():
    modo = "SMTP real" if recordatorio.smtp_configurado() else "modo demostración"
    reintentos = recordatorio.procesar_pendientes(sincrono=True)
    n = recordatorio.enviar_manana(sincrono=True)
    print(f"Recordatorios ({modo}): {n} procesados, {reintentos} reintentos de la cola.")
