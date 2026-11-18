"""Configuración central de la aplicación (lee variables desde .env)."""
import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(valor, defecto=False):
    if valor is None or valor == "":
        return defecto
    return str(valor).strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# Claves de ejemplo que nunca deben usarse fuera de desarrollo
CLAVES_INSEGURAS = {
    "", "cambia-esta-clave-en-produccion", "cambia-esta-clave-por-una-larga-y-aleatoria",
    "dev-solo-desarrollo-no-usar-en-produccion",
}


class Config:
    # Entorno: development | production. Por defecto production (seguro): en desarrollo
    # defina APP_ENV=development en .env.
    APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
    DEV_MODE = APP_ENV == "development"

    # Fuera de desarrollo SECRET_KEY es obligatoria (create_app no arranca sin ella).
    SECRET_KEY = os.getenv("SECRET_KEY") or ("dev-solo-desarrollo-no-usar-en-produccion" if DEV_MODE else None)

    # Zona horaria del negocio: define "hoy" y "ahora" en toda la aplicación.
    TZ = os.getenv("TZ", "America/Bogota").strip() or "America/Bogota"

    # Base de datos
    DB_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()   # mysql | sqlite
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "db_citas_medicas")
    SQLITE_PATH = os.getenv("SQLITE_PATH", "citas.db")
    if not os.path.isabs(SQLITE_PATH):
        SQLITE_PATH = os.path.join(BASE_DIR, SQLITE_PATH)

    # Agenda
    SLOT_MINUTES = int(os.getenv("SLOT_MINUTES", "30"))
    # Horas mínimas de anticipación para que un paciente cancele o reprograme
    ANTICIPACION_HORAS = int(os.getenv("ANTICIPACION_HORAS", "2"))
    # Minutos después de la hora de la cita a partir de los cuales se puede marcar Inasistida
    TOLERANCIA_INASISTENCIA_MIN = int(os.getenv("TOLERANCIA_INASISTENCIA_MIN", "15"))
    # 1 = hilo en segundo plano que envía recordatorios de las citas de mañana (cada hora)
    AUTO_REMINDERS = _bool(os.getenv("AUTO_REMINDERS"), False)

    # Listados y reportes
    PAGE_SIZE = int(os.getenv("PAGE_SIZE", "20"))
    REPORT_MAX_ROWS = int(os.getenv("REPORT_MAX_ROWS", "5000"))

    # Inicio de sesión y recuperación de contraseña
    LOGIN_MAX_INTENTOS = int(os.getenv("LOGIN_MAX_INTENTOS", "5"))
    LOGIN_VENTANA_MIN = int(os.getenv("LOGIN_VENTANA_MIN", "15"))
    RESET_TOKEN_MIN = int(os.getenv("RESET_TOKEN_MIN", "30"))

    # Correo (opcional)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "").strip()
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool(os.getenv("MAIL_USE_TLS"), True)
    MAIL_USER = os.getenv("MAIL_USER", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "citas@ucc.edu.co")
    # 1 = los correos salen en un hilo en segundo plano (en pruebas se fuerza a síncrono)
    MAIL_ASYNC = _bool(os.getenv("MAIL_ASYNC"), True)

    # Sesión
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.getenv("SESSION_COOKIE_SECURE"), False)   # 1 detrás de HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
