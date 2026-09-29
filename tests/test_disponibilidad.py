"""Tests de la función de disponibilidad (pura: no necesita base de datos).

Correr con:  pytest
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.disponibilidad import horarios_libres

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DIA = date(2026, 10, 6)                          # un martes
AYER = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)   # "ahora" = el día anterior


def h(hhmm: str) -> datetime:
    return datetime.combine(DIA, time.fromisoformat(hhmm), tzinfo=TZ)


def horas(resultado):
    return [r.strftime("%H:%M") for r in resultado]


def test_franja_vacia_ofrece_cada_15_minutos():
    r = horarios_libres(DIA, 30, [(time(10), time(11))], [], TZ, AYER)
    assert horas(r) == ["10:00", "10:15", "10:30"]   # 10:45 no: terminaría 11:15


def test_el_servicio_tiene_que_entrar_completo():
    # Combo de 50' en una franja de 1 hora: solo entra a las 10:00.
    r = horarios_libres(DIA, 50, [(time(10), time(11))], [], TZ, AYER)
    assert horas(r) == ["10:00"]


def test_turno_ocupado_bloquea_los_horarios_que_lo_pisan():
    ocupado = [(h("10:30"), h("11:00"))]
    r = horarios_libres(DIA, 30, [(time(10), time(12))], ocupado, TZ, AYER)
    # 10:15 terminaría 10:45 (pisa). 10:00 termina justo 10:30 (no pisa).
    assert "10:00" in horas(r)
    assert "10:15" not in horas(r)
    assert "10:30" not in horas(r)
    assert "11:00" in horas(r)


def test_dos_franjas_respeta_el_corte_del_mediodia():
    r = horarios_libres(DIA, 30, [(time(15), time(16)), (time(10), time(11))], [], TZ, AYER)
    assert horas(r) == ["10:00", "10:15", "10:30", "15:00", "15:15", "15:30"]


def test_no_ofrece_horarios_pasados_ni_demasiado_cercanos():
    ahora = h("10:10")   # con 60' de anticipación mínima, lo primero es 11:15
    r = horarios_libres(DIA, 30, [(time(10), time(12))], [], TZ, ahora, anticipacion_min=60)
    assert horas(r)[0] == "11:15"


def test_bloqueo_de_todo_el_dia():
    bloqueo = [(h("00:00"), h("23:59"))]
    assert horarios_libres(DIA, 30, [(time(10), time(20))], bloqueo, TZ, AYER) == []


def test_normalizar_telefono_argentino():
    from app.schemas import normalizar_telefono
    for escrito in ("+54 9 11 2233-4455", "5491122334455", "011 2233 4455", "11 2233-4455"):
        assert normalizar_telefono(escrito) == "1122334455"
