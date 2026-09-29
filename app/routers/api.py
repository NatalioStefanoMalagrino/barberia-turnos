"""API pública: la usa el formulario de reserva de la landing (JavaScript)."""
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.config import BASE_URL, TZ
from app.db import engine, transaccion
from app.schemas import ReservaIn
from app.turnos import (TurnoNoDisponible, crear_turno, disponibilidad_por_barbero,
                        fecha_reservable, servicio_activo)

router = APIRouter(prefix="/api", tags=["reservas"])


@router.get("/servicios")
def listar_servicios():
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT id, nombre, descripcion, duracion_min, precio
            FROM servicio WHERE activo ORDER BY orden, nombre
        """)).mappings().all()


@router.get("/barberos")
def listar_barberos():
    with engine.connect() as conn:
        return conn.execute(text("SELECT id, nombre FROM barbero WHERE activo ORDER BY id")).mappings().all()


@router.get("/disponibilidad")
def disponibilidad(
    servicio_id: int,
    fecha: date,
    barbero_id: int | None = Query(None, description="Vacío = cualquier barbero"),
):
    """Horarios libres de un día para un servicio.

    Si no se elige barbero, se combinan las agendas: un horario aparece si
    AL MENOS un barbero lo tiene libre, y se informa cuáles.
    """
    if not fecha_reservable(fecha):
        return {"fecha": fecha, "horarios": []}
    with engine.connect() as conn:
        try:
            servicio = servicio_activo(conn, servicio_id)
        except TurnoNoDisponible as e:
            raise HTTPException(404, str(e))
        libres = disponibilidad_por_barbero(conn, fecha, servicio["duracion_min"], barbero_id)

    por_hora: dict = {}
    for b_id, inicios in libres.items():
        for ini in inicios:
            por_hora.setdefault(ini, []).append(b_id)

    return {
        "fecha": fecha,
        "horarios": [
            {"hora": ini.strftime("%H:%M"), "inicio": ini.isoformat(), "barberos": sorted(bs)}
            for ini, bs in sorted(por_hora.items())
        ],
    }


@router.post("/turnos", status_code=201)
def reservar(datos: ReservaIn):
    try:
        with transaccion(actor="cliente") as conn:
            t = crear_turno(conn, **datos.model_dump(), origen="web")
            detalle = conn.execute(text("""
                SELECT b.nombre AS barbero, s.nombre AS servicio
                FROM barbero b, servicio s WHERE b.id = :b AND s.id = :s
            """), {"b": t["barbero_id"], "s": datos.servicio_id}).mappings().one()
    except TurnoNoDisponible as e:
        # 409 Conflict: el pedido es válido pero choca con el estado actual.
        raise HTTPException(409, str(e))

    inicio = t["inicio"].astimezone(TZ)
    return {
        "id": t["id"],
        "inicio": inicio.isoformat(),
        "barbero": detalle["barbero"],
        "servicio": detalle["servicio"],
        "link_turno": f"{BASE_URL}/turno/{t['token_cancelacion']}",
    }
