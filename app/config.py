"""Configuración de la app.

Dos fuentes:
  * Variables de entorno (.env): lo secreto y lo que cambia entre
    entornos (conexión a la base, clave de sesión, URL pública).
  * config/negocio.json: los datos de la barbería que muestra la landing.
    Para otro cliente se cambia ese archivo y no se toca código.
"""
import json
import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta: Path) -> None:
    """Lector mínimo de .env (para no sumar otra dependencia)."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env(RAIZ / ".env")


def _normalizar_url(url: str) -> str:
    """Los hostings (Render, Railway, Heroku) dan la URL como
    'postgres://...' o 'postgresql://...'. SQLAlchemy necesita que se le
    diga qué driver usar ('postgresql+psycopg://'). Lo arreglamos acá para
    que nadie tenga que editar la URL a mano."""
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


DATABASE_URL = _normalizar_url(os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/barberia"
))
SECRET_KEY = os.environ.get("SECRET_KEY", "solo-para-desarrollo")
# Render define RENDER_EXTERNAL_URL solo con la URL pública del servicio,
# así no hay que configurar BASE_URL a mano después del primer deploy.
BASE_URL = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
            or "http://localhost:8000").rstrip("/")

# Primer arranque en la nube (ver app/arranque.py):
#  ADMIN_PASSWORD: contraseña del usuario "dueno" del panel.
#  CARGAR_DEMO:    "true" = cargar 6 meses de datos simulados si la base está vacía.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
CARGAR_DEMO = os.environ.get("CARGAR_DEMO", "").lower() in ("1", "true", "si", "sí")


@lru_cache
def negocio() -> dict:
    with open(RAIZ / "config" / "negocio.json", encoding="utf-8") as f:
        return json.load(f)


TZ = ZoneInfo(negocio()["zona_horaria"])
PASO_MIN = negocio()["reservas"]["paso_minutos"]
ANTICIPACION_MIN = negocio()["reservas"]["anticipacion_minima_minutos"]
DIAS_ADELANTE = negocio()["reservas"]["dias_hacia_adelante"]
