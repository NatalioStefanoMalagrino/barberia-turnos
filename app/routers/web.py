"""Páginas públicas: la landing y la página del turno (ver / cancelar)."""
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.config import TZ, negocio
from app.db import engine, transaccion
from app.plantillas import templates
from app.turnos import ahora

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    with engine.connect() as conn:
        servicios = conn.execute(text(
            "SELECT id, nombre, descripcion, duracion_min, precio FROM servicio WHERE activo ORDER BY orden"
        )).mappings().all()
        barberos = conn.execute(text("SELECT id, nombre FROM barbero WHERE activo ORDER BY id")).mappings().all()
    return templates.TemplateResponse(request, "index.html", {
        "negocio": negocio(), "servicios": servicios, "barberos": barberos,
    })


def _buscar_turno(conn, token: UUID):
    return conn.execute(text("""
        SELECT t.id, t.inicio, t.fin, t.estado, t.precio_cobrado,
               s.nombre AS servicio, b.nombre AS barbero, c.nombre AS cliente
        FROM turno t
        JOIN servicio s ON s.id = t.servicio_id
        JOIN barbero  b ON b.id = t.barbero_id
        JOIN cliente  c ON c.id = t.cliente_id
        WHERE t.token_cancelacion = :token
    """), {"token": token}).mappings().first()


@router.get("/turno/{token}", response_class=HTMLResponse)
def ver_turno(request: Request, token: UUID, cancelado: bool = False):
    with engine.connect() as conn:
        turno = _buscar_turno(conn, token)
    if turno is None:
        return templates.TemplateResponse(request, "turno.html",
                                          {"negocio": negocio(), "turno": None}, status_code=404)
    puede_cancelar = turno["estado"] == "reservado" and turno["inicio"] > ahora()
    return templates.TemplateResponse(request, "turno.html", {
        "negocio": negocio(), "turno": turno, "inicio": turno["inicio"].astimezone(TZ),
        "puede_cancelar": puede_cancelar, "recien_cancelado": cancelado,
    })


@router.post("/turno/{token}/cancelar")
def cancelar_turno(token: UUID):
    # El token es un UUID aleatorio: adivinarlo es inviable, así que
    # funciona como "contraseña" del turno sin pedirle login al cliente.
    with transaccion(actor="cliente") as conn:
        conn.execute(text("""
            UPDATE turno SET estado = 'cancelado'
            WHERE token_cancelacion = :token AND estado = 'reservado' AND inicio > now()
        """), {"token": token})
    # Patrón POST -> redirect -> GET: si el usuario recarga la página, no
    # se reenvía el formulario.
    return RedirectResponse(f"/turno/{token}?cancelado=1", status_code=303)
