"""Crea la base de datos, aplica las migraciones pendientes y (opcionalmente) los datos de demostración.

Uso:   python init_db.py                 aplica migraciones; siembra demo solo si APP_ENV=development
       python init_db.py --demo          fuerza la siembra de datos de demostración
       python init_db.py --sin-demo      nunca siembra datos de demostración
       python init_db.py --reset         BORRA y recrea todo (solo desarrollo)
       python init_db.py --admin CORREO  crea un administrador (pide nombre, documento y contraseña)

Migraciones: migrations/NNN_nombre.<motor>.sql (motor = sqlite | mysql). Se aplican en orden
y cada versión aplicada queda en la tabla schema_migrations.
"""
import getpass
import glob
import os
import re
import sqlite3
import sys
from datetime import timedelta

from config import BASE_DIR, Config

MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")
SEED_FILE = os.path.join(BASE_DIR, "seed_demo.sql")


def _sentencias(texto):
    """Quita comentarios de línea y separa por ';' al final de línea."""
    lineas = [l for l in texto.splitlines() if not l.strip().startswith("--")]
    texto = "\n".join(lineas)
    return [s.strip().rstrip(";").strip() for s in (texto + "\n").split(";\n") if s.strip().rstrip(";").strip()]


def migraciones(engine):
    """[(version, nombre, ruta)] ordenadas para el motor indicado."""
    out = []
    for ruta in glob.glob(os.path.join(MIGRATIONS_DIR, f"*.{engine}.sql")):
        m = re.match(r"(\d{3})_([a-z0-9_]+)\." + engine + r"\.sql$", os.path.basename(ruta))
        if m:
            out.append((int(m.group(1)), m.group(2), ruta))
    out.sort()
    versiones = [v for v, _, _ in out]
    if len(versiones) != len(set(versiones)):
        sys.exit(f"Hay migraciones con número repetido en {MIGRATIONS_DIR}.")
    return out


# ---------------- Adaptadores por motor ----------------
class _SQLite:
    ph = "?"

    def __init__(self, path):
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def ex(self, sql, p=()):
        self.conn.execute(sql, p)

    def one(self, sql, p=()):
        r = self.conn.execute(sql, p).fetchone()
        return dict(r) if r else None

    def crear_tabla_migraciones(self):
        self.ex("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, nombre TEXT NOT NULL, "
                "aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

    def aplicar(self, version, nombre, sql):
        # DDL transaccional en SQLite: la migración se aplica completa o no se aplica.
        try:
            self.conn.executescript("BEGIN;\n" + sql + "\n;INSERT INTO schema_migrations (version, nombre) "
                                    f"VALUES ({int(version)}, '{nombre}');\nCOMMIT;")
        except Exception:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise

    def script(self, sql):
        sql = sql.replace("INSERT IGNORE", "INSERT OR IGNORE")
        for s in _sentencias(sql):
            self.ex(s)

    def close(self):
        self.conn.close()


class _MySQL:
    ph = "%s"

    def __init__(self, cfg, reset):
        try:
            import pymysql
            import pymysql.cursors
        except ImportError:
            sys.exit("Falta PyMySQL. Ejecute:  pip install -r requirements.txt")
        try:
            self.conn = pymysql.connect(host=cfg.DB_HOST, user=cfg.DB_USER, password=cfg.DB_PASSWORD,
                                        port=cfg.DB_PORT, charset="utf8mb4",
                                        cursorclass=pymysql.cursors.DictCursor, connect_timeout=5, autocommit=True)
        except Exception as exc:
            sys.exit(f"No se pudo conectar a MySQL ({cfg.DB_HOST}:{cfg.DB_PORT}) con el usuario '{cfg.DB_USER}'.\n"
                     f"Detalle: {exc}\n-> Encienda MySQL (XAMPP) y revise DB_USER / DB_PASSWORD en el archivo .env\n"
                     "-> O pruebe sin MySQL poniendo DB_ENGINE=sqlite en .env")
        self.cur = self.conn.cursor()
        if reset:
            self.cur.execute(f"DROP DATABASE IF EXISTS `{cfg.DB_NAME}`")
        self.cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg.DB_NAME}` CHARACTER SET utf8mb4 "
                         "COLLATE utf8mb4_unicode_ci")
        self.cur.execute(f"USE `{cfg.DB_NAME}`")

    def ex(self, sql, p=()):
        self.cur.execute(sql, p)

    def one(self, sql, p=()):
        self.cur.execute(sql, p)
        return self.cur.fetchone()

    def crear_tabla_migraciones(self):
        self.ex("CREATE TABLE IF NOT EXISTS schema_migrations (version INT PRIMARY KEY, nombre VARCHAR(100) NOT NULL, "
                "aplicada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB")

    def aplicar(self, version, nombre, sql):
        # En MySQL el DDL hace commit implícito: si una sentencia falla, revise el estado antes de reintentar.
        for s in _sentencias(sql):
            self.ex(s)
        self.ex("INSERT INTO schema_migrations (version, nombre) VALUES (%s, %s)", (version, nombre))

    def script(self, sql):
        for s in _sentencias(sql):
            self.ex(s)

    def close(self):
        self.conn.close()


def conectar(cfg, reset=False):
    if cfg.DB_ENGINE == "sqlite":
        if reset and os.path.exists(cfg.SQLITE_PATH):
            os.remove(cfg.SQLITE_PATH)
        return _SQLite(cfg.SQLITE_PATH), cfg.SQLITE_PATH
    if cfg.DB_ENGINE == "mysql":
        return _MySQL(cfg, reset), f"MySQL {cfg.DB_HOST}:{cfg.DB_PORT}/{cfg.DB_NAME}"
    sys.exit("DB_ENGINE debe ser 'mysql' o 'sqlite'.")


def aplicar_migraciones(db, engine):
    db.crear_tabla_migraciones()
    aplicadas = []
    for version, nombre, ruta in migraciones(engine):
        if db.one(f"SELECT version FROM schema_migrations WHERE version = {db.ph}", (version,)):
            continue
        with open(ruta, encoding="utf-8") as f:
            db.aplicar(version, nombre, f.read())
        aplicadas.append(f"{version:03d}_{nombre}")
    return aplicadas


# ---------------- Datos de demostración ----------------
def _proximo_dia_habil(desde, dias):
    d = desde
    while dias > 0 or d.weekday() > 4:
        d += timedelta(days=1)
        if d.weekday() <= 4:
            dias -= 1
    return d


def citas_demo():
    """Citas de ejemplo con fechas relativas a hoy (en la zona del negocio) y siempre dentro de horario."""
    from app.utils import hoy
    h = hoy()
    return [
        (_proximo_dia_habil(h, 1), "09:00:00", "medico@citas.com", "paciente@citas.com", "Pendiente", "Control cardiovascular rutinario"),
        (_proximo_dia_habil(h, 1), "10:30:00", "sofia@citas.com", "juan@citas.com", "Pendiente", "Dolor de cabeza persistente"),
        (_proximo_dia_habil(h, 3), "08:30:00", "sofia@citas.com", "paciente@citas.com", "Pendiente", "Chequeo general"),
        (h - timedelta(days=4), "08:00:00", "sofia@citas.com", "paciente@citas.com", "Atendida", "Chequeo general inicial"),
        (h - timedelta(days=2), "15:00:00", "medico@citas.com", "juan@citas.com", "Inasistida", "Revisión de presión arterial"),
    ]


def sembrar_demo(db):
    with open(SEED_FILE, encoding="utf-8") as f:
        db.script(f.read())
    if db.one("SELECT COUNT(*) AS n FROM citas")["n"]:
        return 0
    ph, n = db.ph, 0
    for fecha, hora, prof, pac, estado, motivo in citas_demo():
        p = db.one(f"SELECT id FROM usuarios WHERE correo = {ph}", (prof,))
        a = db.one(f"SELECT id FROM usuarios WHERE correo = {ph}", (pac,))
        db.ex(f"INSERT INTO citas (paciente_id, profesional_id, fecha, hora, estado, motivo) "
              f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph})", (a["id"], p["id"], fecha.isoformat(), hora, estado, motivo))
        n += 1
    c = db.one("SELECT c.id, c.profesional_id FROM citas c WHERE c.estado = 'Atendida' LIMIT 1")
    if c:
        db.ex(f"INSERT INTO historial_citas (cita_id, observacion, registrado_por) VALUES ({ph},{ph},{ph})",
              (c["id"], "Paciente en buen estado general. Se recomienda control en 6 meses.", c["profesional_id"]))
    return n


def crear_admin(db, correo):
    from werkzeug.security import generate_password_hash
    nombre = input("Nombre completo: ").strip()
    documento = input("Documento: ").strip()
    pw = getpass.getpass("Contraseña (mín. 8): ")
    if len(pw) < 8 or pw != getpass.getpass("Repita la contraseña: "):
        sys.exit("Contraseña inválida o no coincide.")
    db.ex(f"INSERT INTO usuarios (nombre, documento, correo, password_hash, rol) VALUES "
          f"({db.ph},{db.ph},{db.ph},{db.ph},'administrador')",
          (nombre, documento, correo.lower(), generate_password_hash(pw, method="pbkdf2:sha256")))
    print(f"[OK] Administrador {correo} creado.")


def main(reset=False, demo=None, admin=None):
    cfg = Config
    if demo is None:
        demo = cfg.APP_ENV == "development"
    db, destino = conectar(cfg, reset)
    try:
        aplicadas = aplicar_migraciones(db, cfg.DB_ENGINE)
        n = sembrar_demo(db) if demo else 0
        if admin:
            crear_admin(db, admin)
    finally:
        db.close()
    print(f"[OK] Base de datos lista en {destino}")
    print(f"[OK] Migraciones aplicadas: {', '.join(aplicadas) if aplicadas else 'ninguna (ya estaba al día)'}")
    print(f"[OK] Datos de demostración: {'sí' if demo else 'no'} · citas demo insertadas: {n}")
    print("  Ahora ejecute:  python run.py   y abra http://127.0.0.1:5000")


if __name__ == "__main__":
    args = sys.argv[1:]
    admin = args[args.index("--admin") + 1] if "--admin" in args and args.index("--admin") + 1 < len(args) else None
    main(reset="--reset" in args,
         demo=True if "--demo" in args else (False if "--sin-demo" in args else None),
         admin=admin)
