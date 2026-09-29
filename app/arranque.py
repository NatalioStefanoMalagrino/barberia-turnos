"""Preparación automática de la base en el primer arranque.

Permite subir el sistema a la nube sin correr ningún comando a mano:
al iniciar, la app se fija en qué estado está la base y completa lo que
falte. Todo es IDEMPOTENTE: si ya está hecho, no hace nada, así que se
puede reiniciar la app las veces que haga falta sin romper nada.

  1. Si no existen las tablas            -> ejecuta db/01_schema.sql y 02_seed.sql
  2. Si hay ADMIN_PASSWORD y no existe "dueno" -> crea el usuario del panel
  3. Si CARGAR_DEMO=true y no hay turnos -> genera datos simulados y corre el ETL
"""
import logging

from sqlalchemy import text

from app.config import ADMIN_PASSWORD, CARGAR_DEMO
from app.db import engine

log = logging.getLogger("uvicorn.error")

# Número arbitrario para el "candado" de PostgreSQL. Si por algún motivo
# arrancan dos copias de la app a la vez, solo una prepara la base; la otra
# espera y después ve que ya está todo hecho.
CANDADO = 20260929


def preparar_base() -> None:
    from app.cli import crear_usuario, inicializar_db

    # AUTOCOMMIT: cada consulta de chequeo cierra su transacción enseguida.
    # Si no, el SELECT sobre "turno" dejaría un bloqueo abierto y el TRUNCATE
    # del generador de datos (en otra conexión) esperaría para siempre.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": CANDADO})
        try:
            if conn.execute(text("SELECT to_regclass('public.turno')")).scalar() is None:
                log.info("Base vacía: creando tablas y datos iniciales")
                inicializar_db()

            existe_dueno = conn.execute(
                text("SELECT 1 FROM usuario_panel WHERE usuario = 'dueno'")).scalar()
            if ADMIN_PASSWORD and not existe_dueno:
                crear_usuario("dueno", ADMIN_PASSWORD, None)
                log.info("Usuario 'dueno' creado")

            hay_turnos = conn.execute(text("SELECT EXISTS (SELECT 1 FROM turno)")).scalar()
            if CARGAR_DEMO and not hay_turnos:
                from data import etl, generar_datos
                log.info("Cargando datos de demo")
                generar_datos.main(confirmado=True)
                etl.correr()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CANDADO})
