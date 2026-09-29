"""Motor de plantillas HTML (Jinja2) con algunos filtros en castellano."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.schemas import link_whatsapp

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def pesos(valor) -> str:
    """12000 -> '$ 12.000' (formato argentino)."""
    return "$ " + f"{float(valor):,.0f}".replace(",", ".")


def fecha_larga(d) -> str:
    """-> 'martes 6 de octubre'"""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


templates.env.filters["pesos"] = pesos
templates.env.filters["fecha_larga"] = fecha_larga
templates.env.filters["whatsapp"] = link_whatsapp
