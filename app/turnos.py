"""Lógica de turnos que comparten la API pública y el panel del barbero.

Separarla de los endpoints permite reusarla (la web y el panel crean
turnos de la misma forma) y testearla sin levantar el servidor.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from psycopg.errors import ExclusionViolation
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import ANTICIPACION_MIN, DIAS_ADELANTE, PASO_MIN, TZ
from app.disponibilidad import horarios_libres


class TurnoNoDisponible(Exception):
    """El horario pedido no está libre (o dejó de estarlo)."""


def ahora() -> datetime:
    return datetime.now(TZ)


def _limites_del_dia(fecha: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(fecha, time.min, tzinfo=TZ)
    return inicio, inicio + timedelta(days=1)


def servicio_activo(conn, servicio_id: int):
    fila = conn.execute(
        text("SELECT id, nombre, duracion_min, precio FROM servicio WHERE id = :id AND activo"),
        {"id": servicio_id},
    ).mappings().first()
    if fila is None:
        raise TurnoNoDisponible("Ese servicio no existe.")
    return fila


def disponibilidad_por_barbero(
    conn, fecha: date, duracion_min: int, barbero_id: int | None = None,
    anticipacion_min: int = ANTICIPACION_MIN,
) -> dict[int, list[datetime]]:
    """Para cada barbero activo: lista de inicios libres ese día.

    Hace 3 consultas (franjas, turnos, bloqueos) para TODOS los barberos
    juntos, en vez de 3 por barbero. Con 3 barberos da igual, pero es el
    hábito correcto: evitar el problema "N+1 consultas".
    """
    desde, hasta = _limites_del_dia(fecha)
    filtro = "AND b.id = :barbero_id" if barbero_id else ""
    params = {"dia": fecha.isoweekday(), "desde": desde, "hasta": hasta, "barbero_id": barbero_id}

    franjas = defaultdict(list)
    for f in conn.execute(text(f"""
        SELECT h.barbero_id, h.hora_desde, h.hora_hasta
        FROM horario_barbero h JOIN barbero b ON b.id = h.barbero_id
        WHERE b.activo AND h.dia_semana = :dia {filtro}
    """), params):
        franjas[f.barbero_id].append((f.hora_desde, f.hora_hasta))

    ocupados = defaultdict(list)
    for o in conn.execute(text("""
        SELECT barbero_id, inicio, fin FROM turno
        WHERE estado <> 'cancelado' AND inicio < :hasta AND fin > :desde
        UNION ALL
        SELECT barbero_id, desde, hasta FROM bloqueo
        WHERE desde < :hasta AND hasta > :desde
    """), params):
        ocupados[o.barbero_id].append((o.inicio, o.fin))

    momento = ahora()
    return {
        b_id: horarios_libres(fecha, duracion_min, fr, ocupados[b_id], TZ, momento,
                              PASO_MIN, anticipacion_min)
        for b_id, fr in franjas.items()
    }


def fecha_reservable(fecha: date) -> bool:
    hoy = ahora().date()
    return hoy <= fecha <= hoy + timedelta(days=DIAS_ADELANTE)


def buscar_o_crear_cliente(conn, nombre: str, telefono: str, email: str | None) -> int:
    """Upsert por teléfono.

    ON CONFLICT hace el "si existe actualizo, si no inserto" en UNA sola
    sentencia atómica. Hacerlo con un SELECT y después un INSERT tiene una
    condición de carrera: dos reservas simultáneas del mismo cliente nuevo
    intentarían crearlo dos veces.
    Si el cliente ya existía, conservamos su nombre original (no queremos
    que un typo lo pise) y solo completamos el email si antes no había.
    """
    return conn.execute(text("""
        INSERT INTO cliente (nombre, telefono, email)
        VALUES (:nombre, :telefono, :email)
        ON CONFLICT (telefono) DO UPDATE
            SET email = COALESCE(cliente.email, EXCLUDED.email)
        RETURNING id
    """), {"nombre": nombre, "telefono": telefono, "email": email}).scalar_one()


def crear_turno(
    conn, *, servicio_id: int, barbero_id: int | None, inicio: datetime,
    nombre: str, telefono: str, email: str | None = None,
    origen: str = "web", respetar_horario: bool = True,
):
    """Crea un turno y devuelve sus datos.

    respetar_horario=False lo usa el panel: el barbero puede anotar a
    alguien fuera de hora (se quedó un rato más). La regla de NO pisar
    turnos se sigue cumpliendo igual, porque la impone la base.
    """
    servicio = servicio_activo(conn, servicio_id)
    inicio = inicio.astimezone(TZ)
    fin = inicio + timedelta(minutes=servicio["duracion_min"])

    if respetar_horario:
        if not fecha_reservable(inicio.date()):
            raise TurnoNoDisponible("Esa fecha no está habilitada para reservar.")
        libres = disponibilidad_por_barbero(conn, inicio.date(), servicio["duracion_min"], barbero_id)
        candidatos = [b for b, horas in libres.items() if inicio in horas]
        if not candidatos:
            raise TurnoNoDisponible("Ese horario ya no está disponible.")
        if barbero_id is None:
            barbero_id = _barbero_menos_cargado(conn, candidatos, inicio.date())
    elif barbero_id is None:
        raise TurnoNoDisponible("Elegí un barbero.")

    cliente_id = buscar_o_crear_cliente(conn, nombre, telefono, email)

    try:
        # SAVEPOINT: si la constraint rechaza el INSERT, deshacemos solo
        # esta parte y podemos devolver un error prolijo.
        with conn.begin_nested():
            return conn.execute(text("""
                INSERT INTO turno (cliente_id, barbero_id, servicio_id, inicio, fin,
                                   precio_cobrado, origen)
                VALUES (:cliente_id, :barbero_id, :servicio_id, :inicio, :fin, :precio, :origen)
                RETURNING id, inicio, fin, token_cancelacion, barbero_id
            """), {
                "cliente_id": cliente_id, "barbero_id": barbero_id, "servicio_id": servicio_id,
                "inicio": inicio, "fin": fin, "precio": servicio["precio"], "origen": origen,
            }).mappings().one()
    except IntegrityError as e:
        # Llegó otra reserva al mismo horario entre nuestro chequeo y el
        # INSERT. La base lo frenó: el sistema nunca queda con dos turnos pisados.
        if isinstance(e.orig, ExclusionViolation):
            raise TurnoNoDisponible("Alguien acaba de reservar ese horario. Elegí otro.") from e
        raise


def _barbero_menos_cargado(conn, candidatos: list[int], fecha: date) -> int:
    """Si el cliente eligió "cualquiera", repartimos el trabajo:
    le damos el turno al barbero con menos minutos reservados ese día."""
    desde, hasta = _limites_del_dia(fecha)
    cargas = dict(conn.execute(text("""
        SELECT barbero_id, COALESCE(SUM(EXTRACT(EPOCH FROM fin - inicio)), 0)
        FROM turno
        WHERE estado <> 'cancelado' AND inicio >= :desde AND inicio < :hasta
          AND barbero_id = ANY(:ids)
        GROUP BY barbero_id
    """), {"desde": desde, "hasta": hasta, "ids": candidatos}).all())
    return min(candidatos, key=lambda b: (cargas.get(b, 0), b))


def cambiar_estado(conn, turno_id: int, nuevo: str, barbero_id: int | None = None) -> bool:
    """Transiciones permitidas: solo desde 'reservado'.

    Un turno completado no puede volver a reservado, etc. Se valida en el
    WHERE: si el turno no está en 'reservado', el UPDATE no toca ninguna fila.
    barbero_id limita a los turnos propios (un barbero no toca los de otro).
    """
    if nuevo not in ("completado", "ausente", "cancelado"):
        raise ValueError(nuevo)
    filtro = "AND barbero_id = :barbero_id" if barbero_id else ""
    filas = conn.execute(text(f"""
        UPDATE turno SET estado = :nuevo
        WHERE id = :id AND estado = 'reservado' {filtro}
    """), {"nuevo": nuevo, "id": turno_id, "barbero_id": barbero_id}).rowcount
    return filas == 1
