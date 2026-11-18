"""Punto de entrada:  python run.py

El modo debug se controla con FLASK_DEBUG=1 (nunca activo por defecto).
"""
import os

from app import create_app
from config import _bool

app = create_app()

if __name__ == "__main__":
    app.run(debug=_bool(os.getenv("FLASK_DEBUG"), False),
            host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"), port=int(os.getenv("FLASK_RUN_PORT", "5000")))
