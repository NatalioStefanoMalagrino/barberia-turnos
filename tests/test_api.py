"""Tests de punta a punta contra un PostgreSQL real.

Usan la base de TEST_DATABASE_URL (o la de .env). ⚠ La vacían: nunca
apuntar esto a la base de producción.
"""
import os
from datetime import date, timedelta
import pytest

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/barberia_test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.cli import crear_usuario, inicializar_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def cliente():
    url = os.environ["DATABASE_URL"]
    base = url.rsplit("/", 1)[1]
    admin = create_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {base} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {base}"))
    inicializar_db()
    crear_usuario("dueno", "clave-test", None)
    crear_usuario("mati", "clave-test", "Mati")
    return TestClient(app)


def proximo_martes() -> date:
    d = date.today() + timedelta(days=1)
    while d.isoweekday() != 2:
        d += timedelta(days=1)
    return d


def reservar(cliente, inicio, servicio_id=1, barbero_id=1, tel="1122334455"):
    return cliente.post("/api/turnos", json={
        "servicio_id": servicio_id, "barbero_id": barbero_id, "inicio": inicio,
        "nombre": "Cliente Test", "telefono": tel,
    })


def test_lunes_no_hay_horarios(cliente):
    lunes = proximo_martes() - timedelta(days=1)
    r = cliente.get("/api/disponibilidad", params={"servicio_id": 1, "fecha": lunes})
    assert r.json()["horarios"] == []


def test_reserva_y_doble_reserva(cliente):
    fecha = proximo_martes()
    libres = cliente.get("/api/disponibilidad",
                         params={"servicio_id": 1, "fecha": fecha, "barbero_id": 1}).json()["horarios"]
    inicio = libres[0]["inicio"]

    assert reservar(cliente, inicio).status_code == 201
    # El mismo horario, mismo barbero: tiene que rechazarlo.
    assert reservar(cliente, inicio, tel="1133334444").status_code == 409
    # Y ya no aparece como libre para ese barbero.
    libres2 = cliente.get("/api/disponibilidad",
                          params={"servicio_id": 1, "fecha": fecha, "barbero_id": 1}).json()["horarios"]
    assert inicio not in [x["inicio"] for x in libres2]


def test_mismo_telefono_es_el_mismo_cliente(cliente):
    fecha = proximo_martes() + timedelta(days=7)
    libres = cliente.get("/api/disponibilidad", params={"servicio_id": 1, "fecha": fecha}).json()["horarios"]
    reservar(cliente, libres[0]["inicio"], barbero_id=None, tel="+54 11 7777-8888")
    reservar(cliente, libres[5]["inicio"], barbero_id=None, tel="11 7777 8888")
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM cliente WHERE telefono = '1177778888'")).scalar()
    assert n == 1  # "+54 11 7777-8888" y "11 7777 8888" son la misma persona


def test_cancelar_por_link_libera_el_horario(cliente):
    fecha = proximo_martes() + timedelta(days=14)
    libres = cliente.get("/api/disponibilidad",
                         params={"servicio_id": 2, "fecha": fecha, "barbero_id": 3}).json()["horarios"]
    t = reservar(cliente, libres[0]["inicio"], servicio_id=2, barbero_id=3).json()
    token = t["link_turno"].rsplit("/", 1)[1]

    r = cliente.post(f"/turno/{token}/cancelar", follow_redirects=False)
    assert r.status_code == 303
    assert "Cancelado" in cliente.get(f"/turno/{token}").text

    libres2 = cliente.get("/api/disponibilidad",
                          params={"servicio_id": 2, "fecha": fecha, "barbero_id": 3}).json()["horarios"]
    assert libres[0]["inicio"] in [x["inicio"] for x in libres2]

    # El trigger dejó registrado quién canceló.
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        actor = c.execute(text("""
            SELECT e.actor FROM turno_evento e JOIN turno t ON t.id = e.turno_id
            WHERE t.token_cancelacion = :tk AND e.estado_nuevo = 'cancelado'
        """), {"tk": token}).scalar()
    assert actor == "cliente"


def test_panel_requiere_login(cliente):
    r = cliente.get("/panel", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/panel/login"


def test_panel_barbero_marca_asistencia(cliente):
    fecha = proximo_martes()
    r = cliente.post("/panel/login", data={"usuario": "mati", "password": "clave-test"}, follow_redirects=False)
    assert r.status_code == 303
    agenda = cliente.get("/panel", params={"fecha": fecha})
    assert "Cliente Test" in agenda.text

    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.connect() as c:
        turno_id = c.execute(text("SELECT id FROM turno WHERE barbero_id = 1 AND estado = 'reservado' LIMIT 1")).scalar()
    cliente.post(f"/panel/turnos/{turno_id}/estado", data={"estado": "ausente", "fecha": str(fecha)})
    with eng.connect() as c:
        assert c.execute(text("SELECT estado FROM turno WHERE id = :i"), {"i": turno_id}).scalar() == "ausente"
    # Un turno ya marcado no se puede volver a cambiar.
    cliente.post(f"/panel/turnos/{turno_id}/estado", data={"estado": "completado", "fecha": str(fecha)})
    with eng.connect() as c:
        assert c.execute(text("SELECT estado FROM turno WHERE id = :i"), {"i": turno_id}).scalar() == "ausente"
    cliente.post("/panel/logout")


def test_login_incorrecto(cliente):
    r = cliente.post("/panel/login", data={"usuario": "mati", "password": "mal"}, follow_redirects=False)
    assert "error" in r.headers["location"]
