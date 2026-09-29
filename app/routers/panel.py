"""Panel del barbero: agenda del día, marcar asistencia, turnos manuales y bloqueos.

Esta pantalla parece "solo de gestión", pero define la CALIDAD DE LOS
DATOS de todo el proyecto: si el barbero no marca quién vino y quién
faltó, o no carga los turnos que le llegan por WhatsApp, los tableros de
ocupación y ausentismo van a estar mal. Por eso todo se hace con un toque.
"""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import text

from app.config import TZ, negocio
from app.db import engine, transaccion
from app.plantillas import templates
from app.schemas import normalizar_telefono
from app.seguridad import verificar
from app.turnos import TurnoNoDisponible, ahora, cambiar_estado, crear_turno

router = APIRouter(prefix="/panel")


class NoLogueado(Exception):
    """Se transforma en un redirect al login (ver main.py)."""


def usuario_actual(request: Request) -> dict:
    usuario = request.session.get("usuario")
    if not usuario:
        raise NoLogueado()
    return usuario


def _volver(fecha: str | date, msg: str = "", error: str = "") -> RedirectResponse:
    url = f"/panel?fecha={fecha}"
    if msg:
        url += f"&msg={msg}"
    if error:
        url += f"&error={error}"
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- login

@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "panel/login.html", {"negocio": negocio(), "error": error})


@router.post("/login")
def login(request: Request, usuario: str = Form(...), password: str = Form(...)):
    with engine.connect() as conn:
        u = conn.execute(text("""
            SELECT u.id, u.usuario, u.password_hash, u.barbero_id, b.nombre AS barbero
            FROM usuario_panel u LEFT JOIN barbero b ON b.id = u.barbero_id
            WHERE u.usuario = :u AND u.activo
        """), {"u": usuario.strip().lower()}).mappings().first()
    # Mismo mensaje si el usuario no existe o si la contraseña está mal:
    # así no le confirmamos a un atacante qué usuarios existen.
    if u is None or not verificar(password, u["password_hash"]):
        return RedirectResponse("/panel/login?error=Usuario o contraseña incorrectos", status_code=303)
    request.session["usuario"] = {
        "id": u["id"], "usuario": u["usuario"], "barbero_id": u["barbero_id"],
        "nombre": u["barbero"] or "Dueño",
    }
    return RedirectResponse("/panel", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=303)


# --------------------------------------------------------------- agenda

@router.get("", response_class=HTMLResponse)
def agenda(request: Request, fecha: date | None = None, msg: str = "", error: str = "",
           usuario: dict = Depends(usuario_actual)):
    fecha = fecha or ahora().date()
    desde = datetime.combine(fecha, time.min, tzinfo=TZ)
    solo_mio = usuario["barbero_id"]
    filtro = "AND t.barbero_id = :barbero_id" if solo_mio else ""

    with engine.connect() as conn:
        turnos = conn.execute(text(f"""
            SELECT t.id, t.inicio, t.fin, t.estado, t.origen, t.precio_cobrado,
                   t.barbero_id, b.nombre AS barbero, s.nombre AS servicio,
                   c.nombre AS cliente, c.telefono,
                   (SELECT count(*) FROM turno t2
                    WHERE t2.cliente_id = t.cliente_id AND t2.estado = 'completado'
                      AND t2.inicio < t.inicio) AS visitas_previas
            FROM turno t
            JOIN barbero b  ON b.id = t.barbero_id
            JOIN servicio s ON s.id = t.servicio_id
            JOIN cliente c  ON c.id = t.cliente_id
            WHERE t.inicio >= :desde AND t.inicio < :hasta {filtro}
            ORDER BY t.inicio, b.id
        """), {"desde": desde, "hasta": desde + timedelta(days=1), "barbero_id": solo_mio}).mappings().all()
        barberos = conn.execute(text("SELECT id, nombre FROM barbero WHERE activo ORDER BY id")).mappings().all()
        servicios = conn.execute(text(
            "SELECT id, nombre, duracion_min FROM servicio WHERE activo ORDER BY orden")).mappings().all()
        ultimo_etl = None
        if conn.execute(text("SELECT to_regclass('analytics.etl_ejecucion')")).scalar():
            ultimo_etl = conn.execute(text("""
                SELECT fin, estado FROM analytics.etl_ejecucion
                WHERE estado <> 'corriendo' ORDER BY id DESC LIMIT 1
            """)).mappings().first()

    resumen = {e: sum(1 for t in turnos if t["estado"] == e)
               for e in ("reservado", "completado", "ausente", "cancelado")}
    resumen["ingresos"] = sum(t["precio_cobrado"] for t in turnos if t["estado"] == "completado")

    return templates.TemplateResponse(request, "panel/agenda.html", {
        "negocio": negocio(), "usuario": usuario, "fecha": fecha,
        "anterior": fecha - timedelta(days=1), "siguiente": fecha + timedelta(days=1),
        "es_hoy": fecha == ahora().date(), "ahora": ahora(),
        "turnos": turnos, "barberos": barberos, "servicios": servicios,
        "resumen": resumen, "msg": msg, "error": error, "TZ": TZ, "ultimo_etl": ultimo_etl,
    })


@router.post("/actualizar-datos")
def actualizar_datos(fecha: str = Form(""), usuario: dict = Depends(usuario_actual)):
    """Corre el ETL a mano (solo el dueño). Útil en el plan gratis de la
    nube, donde no hay tareas programadas: antes de abrir Power BI se
    toca este botón y el modelo estrella queda al día."""
    if usuario["barbero_id"]:
        raise HTTPException(403, "Solo el dueño puede actualizar los datos")
    from data import etl
    try:
        etl.correr()
    except Exception:
        return _volver(fecha or ahora().date(), error="Falló la actualización de datos (ver logs)")
    return _volver(fecha or ahora().date(), msg="Datos del tablero actualizados")


@router.post("/turnos/{turno_id}/estado")
def marcar_estado(turno_id: int, estado: str = Form(...), fecha: str = Form(...),
                  usuario: dict = Depends(usuario_actual)):
    if estado not in ("completado", "ausente", "cancelado"):
        raise HTTPException(400, "Estado inválido")
    with transaccion(actor="barbero") as conn:
        ok = cambiar_estado(conn, turno_id, estado, usuario["barbero_id"])
    return _volver(fecha, msg="Turno actualizado" if ok else "", error="" if ok else "No se pudo actualizar el turno")


@router.post("/turnos")
def turno_manual(
    fecha: date = Form(...), hora: time = Form(...), servicio_id: int = Form(...),
    barbero_id: int = Form(...), nombre: str = Form(...), telefono: str = Form(...),
    usuario: dict = Depends(usuario_actual),
):
    """Turnos que llegan por WhatsApp, teléfono o gente que entra sin turno.
    Cargarlos es lo que hace que la ocupación medida sea la real."""
    if usuario["barbero_id"] and barbero_id != usuario["barbero_id"]:
        raise HTTPException(403, "Solo podés cargar turnos en tu agenda")
    try:
        tel = normalizar_telefono(telefono)
    except ValueError as e:
        return _volver(fecha, error=str(e))
    try:
        with transaccion(actor="barbero") as conn:
            crear_turno(conn, servicio_id=servicio_id, barbero_id=barbero_id,
                        inicio=datetime.combine(fecha, hora, tzinfo=TZ),
                        nombre=" ".join(nombre.split()).title(), telefono=tel,
                        origen="manual", respetar_horario=False)
    except TurnoNoDisponible as e:
        return _volver(fecha, error=str(e))
    return _volver(fecha, msg="Turno cargado")


@router.post("/bloqueos")
def crear_bloqueo(
    fecha: date = Form(...), desde: time = Form(...), hasta: time = Form(...),
    barbero_id: int = Form(...), motivo: str = Form(""),
    usuario: dict = Depends(usuario_actual),
):
    if usuario["barbero_id"] and barbero_id != usuario["barbero_id"]:
        raise HTTPException(403, "Solo podés bloquear tu agenda")
    if desde >= hasta:
        return _volver(fecha, error="La hora de fin tiene que ser posterior al inicio")
    with transaccion(actor="barbero") as conn:
        conn.execute(text("""
            INSERT INTO bloqueo (barbero_id, desde, hasta, motivo)
            VALUES (:b, :d, :h, :m)
        """), {"b": barbero_id, "d": datetime.combine(fecha, desde, tzinfo=TZ),
               "h": datetime.combine(fecha, hasta, tzinfo=TZ), "m": motivo or None})
    return _volver(fecha, msg="Horario bloqueado")
