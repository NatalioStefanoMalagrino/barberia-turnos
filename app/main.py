"""Punto de entrada de la aplicación.

Para correrla en desarrollo:
    uvicorn app.main:app --reload
Documentación interactiva de la API: http://localhost:8000/docs
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.arranque import preparar_base
from app.config import BASE_URL, SECRET_KEY
from app.routers import api, panel, web


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    # Al arrancar: crear tablas / usuario / datos demo si faltan.
    preparar_base()
    yield


app = FastAPI(title="Turnos Barbería", description="API de reservas y panel del barbero.",
              lifespan=ciclo_de_vida)

# La sesión del panel se guarda en una cookie FIRMADA con SECRET_KEY:
# el navegador la puede ver pero no la puede modificar sin que lo notemos.
# same_site="lax" bloquea que otro sitio mande formularios al panel usando
# la sesión del barbero (protección básica contra CSRF).
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, same_site="lax",
    https_only=BASE_URL.startswith("https"), max_age=60 * 60 * 12,
)

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(web.router)
app.include_router(api.router)
app.include_router(panel.router)


@app.exception_handler(panel.NoLogueado)
def _redirigir_login(request: Request, exc: panel.NoLogueado):
    return RedirectResponse("/panel/login", status_code=303)


@app.get("/salud", include_in_schema=False)
def salud():
    """Lo consulta el hosting (Render/Railway) para saber si la app está viva."""
    return {"ok": True}
