"""Tests de las reglas de negocio del ETL (funciones puras, sin base)."""
from datetime import date, time

import pandas as pd

from data.etl import fact_capacidad, segmentar


def test_segmento_se_mide_contra_el_ritmo_propio():
    # Viene cada 21 días: a los 25 está normal, a los 45 en riesgo, a los 90 perdido.
    assert segmentar(5, 25, 21, False) == "Activo"
    assert segmentar(5, 45, 21, False) == "En riesgo"
    assert segmentar(5, 90, 21, False) == "Perdido"
    # Viene cada 60 días: 45 días sin venir es normal para él.
    assert segmentar(3, 45, 60, False) == "Activo"


def test_segmento_primera_visita():
    assert segmentar(1, 20, None, False) == "Nuevo"
    assert segmentar(1, 80, None, False) == "No volvió"


def test_si_ya_tiene_turno_reservado_no_esta_en_riesgo():
    assert segmentar(5, 60, 21, True) == "Activo"


def test_capacidad_descuenta_bloqueos():
    martes = date(2026, 10, 6)
    horarios = pd.DataFrame([{"barbero_id": 1, "dia_semana": 2, "hora_desde": time(10), "hora_hasta": time(20)}])
    bloqueos = pd.DataFrame([{   # 2 horas de trámite (14 a 16 hora argentina = 17 a 19 UTC)
        "barbero_id": 1,
        "desde": pd.Timestamp("2026-10-06 17:00", tz="UTC"),
        "hasta": pd.Timestamp("2026-10-06 19:00", tz="UTC"),
    }])
    turnos = pd.DataFrame(columns=["barbero_id", "inicio", "fin", "estado"])
    barberos = pd.DataFrame({"barbero_key": [1]})
    cap = fact_capacidad(horarios, bloqueos, turnos, barberos, martes, martes)
    assert cap["minutos_disponibles"].tolist() == [8 * 60]
