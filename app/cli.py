"""Comandos de administración.

    python -m app.cli inicializar-db                      (crea tablas + datos iniciales)
    python -m app.cli crear-usuario dueno                 (dueño: ve a todos)
    python -m app.cli crear-usuario mati --barbero Mati   (solo su agenda)
"""
import argparse
import getpass
from pathlib import Path

from sqlalchemy import text

from app.db import engine, transaccion
from app.seguridad import hashear

DB_DIR = Path(__file__).resolve().parent.parent / "db"


def inicializar_db() -> None:
    """Ejecuta db/01_schema.sql y db/02_seed.sql.

    Usamos la conexión "cruda" de psycopg porque los .sql tienen el
    operador % (módulo) y varias sentencias juntas: pasarlos por
    SQLAlchemy haría que interprete el % como un parámetro.

    Si las tablas ya existen no hace nada: así se puede correr dos veces
    (por ejemplo, desde GitHub Actions) sin romper ni duplicar datos.
    """
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.turno')")).scalar():
            print("La base ya estaba inicializada: no se tocó nada.")
            return
        crudo = conn.connection.driver_connection
        for archivo in ("01_schema.sql", "02_seed.sql"):
            crudo.execute((DB_DIR / archivo).read_text(encoding="utf-8"))
    print("Base inicializada.")


def crear_usuario(usuario: str, password: str, barbero: str | None) -> None:
    with transaccion() as conn:
        barbero_id = None
        if barbero:
            barbero_id = conn.execute(text("SELECT id FROM barbero WHERE nombre = :n"),
                                      {"n": barbero}).scalar_one_or_none()
            if barbero_id is None:
                raise SystemExit(f"No existe el barbero '{barbero}'")
        conn.execute(text("""
            INSERT INTO usuario_panel (usuario, password_hash, barbero_id)
            VALUES (:u, :p, :b)
            ON CONFLICT (usuario) DO UPDATE SET password_hash = EXCLUDED.password_hash,
                                                barbero_id = EXCLUDED.barbero_id
        """), {"u": usuario.lower(), "p": hashear(password), "b": barbero_id})
    print(f"Usuario '{usuario}' listo.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inicializar-db")
    c = sub.add_parser("crear-usuario")
    c.add_argument("usuario")
    c.add_argument("--barbero", help="Nombre del barbero (vacío = dueño)")
    c.add_argument("--password", help="Si no se pasa, se pide por consola")
    args = p.parse_args()
    if args.cmd == "inicializar-db":
        inicializar_db()
    elif args.cmd == "crear-usuario":
        crear_usuario(args.usuario, args.password or getpass.getpass("Contraseña: "), args.barbero)
