"""Capa de acceso a datos: MySQL (PyMySQL) o SQLite con la misma interfaz.

Todas las consultas usan marcadores %s; en SQLite se traducen a '?'.
Las filas se devuelven como dict con fechas/horas ya normalizadas a texto
('YYYY-MM-DD', 'HH:MM', 'YYYY-MM-DD HH:MM').

Transacciones: fuera de `with db.transaction():` cada execute() se confirma solo.
Dentro, todo se confirma al salir del bloque o se revierte si hay una excepción.
* SQLite: la conexión trabaja en autocommit y la transacción usa BEGIN IMMEDIATE
  (toma el bloqueo de escritura al inicio: serializa a los escritores).
* MySQL: `lock_profesional()` hace SELECT ... FOR UPDATE sobre la fila del usuario.
"""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from flask import current_app, g

try:
    import pymysql
    import pymysql.cursors
except ImportError:  # solo es obligatorio cuando DB_ENGINE=mysql
    pymysql = None

IntegrityError = (sqlite3.IntegrityError,) + ((pymysql.err.IntegrityError,) if pymysql else ())

TIME_KEYS = {"hora", "hora_inicio", "hora_fin"}
DATETIME_KEYS = {"created_at", "fecha_registro", "enviado_en", "anulada_en", "ultimo_acceso"}


class DatabaseUnavailable(Exception):
    """No fue posible conectarse a la base de datos."""


def _norm(key, v):
    if isinstance(v, timedelta):
        t = int(v.total_seconds())
        return f"{t // 3600:02d}:{(t % 3600) // 60:02d}"
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        if key in TIME_KEYS:
            return v[:5]
        if key in DATETIME_KEYS:
            return v[:16]
    return v


class Database:
    def __init__(self, conn, engine):
        self.conn, self.engine = conn, engine
        self.in_tx = False

    def _cursor(self, sql, params):
        if self.engine == "sqlite":
            sql = sql.replace("%s", "?")
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        return cur

    @staticmethod
    def _row(row):
        d = dict(row)
        return {k: _norm(k, v) for k, v in d.items()}

    def all(self, sql, params=()):
        cur = self._cursor(sql, params)
        rows = [self._row(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def one(self, sql, params=()):
        cur = self._cursor(sql, params)
        r = cur.fetchone()
        cur.close()
        return self._row(r) if r else None

    def _run(self, sql, params):
        try:
            cur = self._cursor(sql, params)
            res = (cur.lastrowid, cur.rowcount)
            cur.close()
            if not self.in_tx:
                self.conn.commit()
            return res
        except Exception:
            if not self.in_tx:
                self.conn.rollback()
            raise

    def execute(self, sql, params=()):
        """Ejecuta INSERT/UPDATE/DELETE. Devuelve lastrowid. Confirma solo si no hay transacción abierta."""
        return self._run(sql, params)[0]

    def rowcount(self, sql, params=()):
        """Como execute() pero devuelve el número de filas afectadas."""
        return self._run(sql, params)[1]

    @contextmanager
    def transaction(self):
        """Bloque atómico. Las transacciones anidadas se integran en la exterior."""
        if self.in_tx:
            yield self
            return
        if self.engine == "sqlite":
            self.conn.execute("BEGIN IMMEDIATE")
        else:
            self.conn.begin()
        self.in_tx = True
        try:
            yield self
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            self.in_tx = False

    def lock_profesional(self, *usuario_ids):
        """Serializa los cambios sobre la agenda de uno o varios usuarios (ids en orden para evitar interbloqueos).
        En SQLite el BEGIN IMMEDIATE ya tiene el bloqueo de escritura de la base."""
        if self.engine == "mysql":
            for uid in sorted({int(u) for u in usuario_ids if u}):
                self.one("SELECT id FROM usuarios WHERE id=%s FOR UPDATE", (uid,))


def connect(cfg):
    engine = cfg["DB_ENGINE"]
    try:
        if engine == "sqlite":
            conn = sqlite3.connect(cfg["SQLITE_PATH"], timeout=10, isolation_level=None)  # autocommit
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        elif engine == "mysql":
            if pymysql is None:
                raise DatabaseUnavailable("PyMySQL no está instalado. Ejecute: pip install -r requirements.txt")
            conn = pymysql.connect(
                host=cfg["DB_HOST"], user=cfg["DB_USER"], password=cfg["DB_PASSWORD"],
                database=cfg["DB_NAME"], port=cfg["DB_PORT"], charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor, connect_timeout=5,
            )
        else:
            raise DatabaseUnavailable(f"DB_ENGINE inválido: '{engine}' (use mysql o sqlite).")
    except DatabaseUnavailable:
        raise
    except Exception as exc:
        raise DatabaseUnavailable(str(exc)) from exc
    return Database(conn, engine)


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        try:
            db.conn.close()
        except Exception:
            pass


def init_app(app):
    app.teardown_appcontext(close_db)
