"""Validación de lo que llega desde afuera (formularios y API).

Pydantic rechaza datos inválidos ANTES de que lleguen a la base.
Es la primera línea de calidad de datos: un teléfono mal cargado hoy es
un cliente que mañana no podemos reconocer ni contactar.
"""
import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


def normalizar_telefono(valor: str) -> str:
    """Lleva cualquier forma de escribir un celular argentino a UNA sola.

        '+54 9 11 2233-4455'  -> '1122334455'
        '011 2233 4455'       -> '1122334455'
        '11 2233-4455'        -> '1122334455'

    Sin esto, la misma persona escrita de dos formas serían dos clientes
    distintos, y el análisis de retención diría que "no volvió".
    Guardamos el número nacional (código de área + número, sin 0 ni 15);
    para armar el link de WhatsApp se le antepone 549.
    """
    digitos = re.sub(r"\D", "", valor or "")
    if digitos.startswith("549"):
        digitos = digitos[3:]
    elif digitos.startswith("54") and len(digitos) >= 12:
        digitos = digitos[2:]
    digitos = digitos.lstrip("0")
    if not 8 <= len(digitos) <= 15:
        raise ValueError("El teléfono tiene que tener entre 8 y 15 dígitos.")
    return digitos


def link_whatsapp(telefono: str) -> str:
    """Número nacional de 10 dígitos -> formato internacional para wa.me."""
    return f"549{telefono}" if len(telefono) == 10 else telefono


class ReservaIn(BaseModel):
    servicio_id: int
    barbero_id: int | None = None          # None = "me da igual el barbero"
    inicio: datetime                        # ISO 8601 con zona horaria
    nombre: str = Field(min_length=2, max_length=80)
    telefono: str
    email: EmailStr | None = None

    @field_validator("telefono")
    @classmethod
    def _telefono(cls, v: str) -> str:
        return normalizar_telefono(v)

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, v: str) -> str:
        return " ".join(v.split()).title()   # "  juan  PEREZ " -> "Juan Perez"
