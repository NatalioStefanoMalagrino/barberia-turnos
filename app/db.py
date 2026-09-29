"""Conexión a PostgreSQL.

Usamos SQLAlchemy "Core" con SQL escrito a mano (text()) en vez del ORM.
Motivo: el proyecto gira alrededor de la base de datos y queremos ver y
controlar cada consulta. Con el ORM el SQL queda escondido, y para alguien
que va a trabajar en datos conviene tenerlo a la vista.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, text

from app.config import DATABASE_URL

# pool_pre_ping: antes de usar una conexión del pool verifica que siga
# viva. Los Postgres en la nube (como Neon) cortan conexiones
# inactivas y sin esto aparecen errores aleatorios.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@contextmanager
def transaccion(actor: str = "sistema"):
    """Abre una transacción: si algo falla adentro, se deshace todo.

    `actor` queda guardado en la variable de sesión app.actor, que lee el
    trigger de turno_evento para registrar QUIÉN hizo el cambio.
    El tercer parámetro `true` de set_config lo limita a esta transacción.
    """
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.actor', :a, true)"), {"a": actor})
        yield conn
