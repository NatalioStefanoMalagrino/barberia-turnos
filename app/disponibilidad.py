"""Cálculo de horarios libres.

Es una función PURA: recibe datos y devuelve datos, sin tocar la base ni
el reloj del sistema. Eso permite testearla con casos armados a mano
(ver tests/test_disponibilidad.py), que es donde suelen esconderse los
bugs de un sistema de turnos.

Idea:
    libres = franjas de trabajo del día
             − turnos ya tomados
             − bloqueos (vacaciones, francos)
             − lo que ya pasó o está demasiado cerca

y dentro de lo libre, ofrecemos inicios cada `paso_min` minutos donde
entre COMPLETO el servicio pedido (un corte de 30' entra en huecos donde
un combo de 50' no entra).
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Intervalo = tuple[datetime, datetime]


def _se_pisan(a_ini: datetime, a_fin: datetime, b_ini: datetime, b_fin: datetime) -> bool:
    # Intervalos semiabiertos [ini, fin): 10:00-10:30 y 10:30-11:00 NO se pisan.
    # Es exactamente la misma regla que usa la constraint de PostgreSQL.
    return a_ini < b_fin and b_ini < a_fin


def horarios_libres(
    fecha: date,
    duracion_min: int,
    franjas: list[tuple[time, time]],
    ocupados: list[Intervalo],
    tz: ZoneInfo,
    ahora: datetime,
    paso_min: int = 15,
    anticipacion_min: int = 60,
) -> list[datetime]:
    """Devuelve los inicios posibles (con zona horaria) para un barbero y un día."""
    duracion = timedelta(minutes=duracion_min)
    paso = timedelta(minutes=paso_min)
    limite = ahora + timedelta(minutes=anticipacion_min)
    resultado: list[datetime] = []

    for desde, hasta in sorted(franjas):
        # Convertimos la hora "de pared" de la barbería a un instante real.
        # Hacerlo con la zona horaria (y no sumando -3 a mano) evita errores
        # si algún día vuelve el horario de verano.
        inicio = datetime.combine(fecha, desde, tzinfo=tz)
        fin_franja = datetime.combine(fecha, hasta, tzinfo=tz)

        while inicio + duracion <= fin_franja:
            fin = inicio + duracion
            if inicio >= limite and not any(_se_pisan(inicio, fin, o_ini, o_fin) for o_ini, o_fin in ocupados):
                resultado.append(inicio)
            inicio += paso

    return resultado
