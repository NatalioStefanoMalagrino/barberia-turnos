"""Contraseñas del panel.

Nunca se guardan en texto plano: se guarda un hash PBKDF2 con "sal"
aleatoria. PBKDF2 viene en la librería estándar de Python (hashlib) y es
deliberadamente lento, para que adivinar contraseñas por fuerza bruta
sea caro si alguien roba la base.
"""
import hashlib
import hmac
import secrets

ITERACIONES = 390_000


def hashear(password: str) -> str:
    sal = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), sal.encode(), ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal}${dk.hex()}"


def verificar(password: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, hash_hex = guardado.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), sal.encode(), int(iteraciones))
    # compare_digest compara en tiempo constante (evita ataques de timing).
    return hmac.compare_digest(dk.hex(), hash_hex)
