"""ETL: del sistema de turnos al modelo estrella de Power BI.

    python -m data.etl

Pasos:
  1. EXTRAER   las tablas del esquema público (lo que escribe la web).
  2. TRANSFORMAR con pandas: armar dimensiones, hechos y los atributos
     calculados (segmento del cliente, primera visita, capacidad).
  3. CARGAR    en el esquema analytics, TODO en una sola transacción.

Estrategia de carga: "full refresh" (se vacían las tablas y se recargan
enteras). Con el volumen de una barbería (miles de filas) tarda segundos
y es la opción más simple y robusta: si algo cambió en el pasado (un
turno que se marcó tarde como ausente) queda corregido solo. Cuando el
volumen lo justifique (muchas barberías, millones de filas) se pasa a
carga incremental: procesar solo lo modificado desde la última corrida.

Se programa para correr todas las noches (ver .github/workflows/etl.yml).
"""
import json
import time as reloj
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.config import TZ
from app.db import engine

SQL_ESQUEMA = Path(__file__).with_name("analytics_schema.sql")

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]


# ======================================================================
#  1. EXTRACCIÓN
# ======================================================================

def extraer(conn) -> dict[str, pd.DataFrame]:
    """Trae solo las columnas necesarias. Nunca SELECT *: si mañana se
    agrega una columna al sistema, el ETL no se entera ni se rompe."""
    q = lambda sql: pd.read_sql(text(sql), conn)  # noqa: E731
    return {
        "turnos": q("""
            SELECT id AS turno_id, cliente_id, barbero_id, servicio_id, inicio, fin,
                   estado, origen, precio_cobrado, creado_en
            FROM turno
        """),
        "cancelaciones": q("""
            SELECT turno_id, max(ocurrido_en) AS cancelado_en
            FROM turno_evento WHERE estado_nuevo = 'cancelado' GROUP BY turno_id
        """),
        "clientes": q("SELECT id AS cliente_id, nombre, telefono, creado_en FROM cliente"),
        "barberos": q("SELECT id AS barbero_key, nombre, activo FROM barbero"),
        "servicios": q("SELECT id AS servicio_key, nombre, duracion_min, precio AS precio_actual FROM servicio"),
        "horarios": q("SELECT barbero_id, dia_semana, hora_desde, hora_hasta FROM horario_barbero"),
        "bloqueos": q("SELECT barbero_id, desde, hasta FROM bloqueo"),
    }


# ======================================================================
#  2. TRANSFORMACIÓN
# ======================================================================

def a_local(serie: pd.Series) -> pd.Series:
    """La base guarda en UTC; los análisis se hacen en hora de Buenos Aires
    (un turno de las 22 h en UTC es de las 19 h acá: otra franja)."""
    return pd.to_datetime(serie, utc=True).dt.tz_convert(TZ)


def fecha_key(serie_fechas) -> pd.Series:
    return pd.to_datetime(serie_fechas).dt.strftime("%Y%m%d").astype(int)


def dim_fecha(desde: date, hasta: date) -> pd.DataFrame:
    """Una fila por día del rango, TENGA O NO turnos. Si faltaran los días
    vacíos, Power BI no los mostraría y un bache parecería no existir."""
    f = pd.Series(pd.date_range(desde, hasta, freq="D"))
    return pd.DataFrame({
        "fecha_key": fecha_key(f),
        "fecha": f.dt.date,
        "anio": f.dt.year,
        "mes": f.dt.month,
        "mes_nombre": f.dt.month.map(lambda m: MESES[m - 1]),
        "anio_mes": f.dt.strftime("%Y-%m"),
        "semana_iso": f.dt.isocalendar().week.astype(int).values,
        "dia_semana_num": f.dt.dayofweek + 1,
        "dia_semana": f.dt.dayofweek.map(lambda d: DIAS[d]),
        "es_fin_de_semana": f.dt.dayofweek >= 5,
    })


def franja(hora: int) -> str:
    if hora < 12:
        return "Mañana"
    if hora < 15:
        return "Mediodía"
    if hora < 17:
        return "Tarde"
    if hora < 20:
        return "Salida del trabajo"
    return "Noche"


def dim_hora() -> pd.DataFrame:
    return pd.DataFrame({"hora": range(24), "franja": [franja(h) for h in range(24)]})


def dim_estado() -> pd.DataFrame:
    return pd.DataFrame([
        ("reservado", "Pendiente: todavía no llegó la fecha", True),
        ("completado", "El cliente vino y fue atendido", True),
        ("ausente", "No vino y no avisó (faltazo)", True),
        ("cancelado", "Avisó que no venía: el horario se liberó", False),
    ], columns=["estado", "descripcion", "ocupa_agenda"])


def fact_turno(turnos: pd.DataFrame, cancelaciones: pd.DataFrame) -> pd.DataFrame:
    t = turnos.merge(cancelaciones, on="turno_id", how="left")
    inicio = a_local(t["inicio"])
    fin = a_local(t["fin"])

    # Primera visita = el primer turno NO cancelado de cada cliente.
    # (Si reservó y canceló, todavía no lo conocemos.)
    no_cancelado = t["estado"] != "cancelado"
    orden = t[no_cancelado].sort_values("inicio").groupby("cliente_id").cumcount()
    es_primera = pd.Series(False, index=t.index)
    es_primera.loc[orden[orden == 0].index] = True

    precio = t["precio_cobrado"].astype(float)
    horas = lambda td: (td.dt.total_seconds() / 3600).round(1)  # noqa: E731

    return pd.DataFrame({
        "turno_id": t["turno_id"],
        "fecha_key": fecha_key(inicio.dt.date),
        "hora": inicio.dt.hour,
        "barbero_key": t["barbero_id"],
        "servicio_key": t["servicio_id"],
        "cliente_key": t["cliente_id"],
        "estado": t["estado"],
        "origen": t["origen"],
        "precio": precio,
        "ingreso": precio.where(t["estado"] == "completado", 0.0),
        "ingreso_perdido": precio.where(t["estado"] == "ausente", 0.0),
        "duracion_min": ((fin - inicio).dt.total_seconds() // 60).astype(int),
        "anticipacion_horas": horas(inicio - a_local(t["creado_en"])).clip(lower=0),
        "cancelacion_anticipacion_horas": horas(inicio - a_local(t["cancelado_en"])),
        "es_primera_visita": es_primera,
        "completado": (t["estado"] == "completado").astype(int),
        "ausente": (t["estado"] == "ausente").astype(int),
        "cancelado": (t["estado"] == "cancelado").astype(int),
    })


# Orden en que se muestran los segmentos en los gráficos.
SEGMENTOS = {"Nuevo": 1, "Activo": 2, "En riesgo": 3, "Perdido": 4, "No volvió": 5, "Sin visitas": 6}


def segmentar(visitas: int, dias_desde_ultima, frecuencia, tiene_turno_futuro: bool) -> str:
    """Reglas de segmentación (explicadas en docs/04-datos.md).

    La clave es comparar a cada cliente CONTRA SU PROPIO RITMO y no contra
    un promedio general: alguien que viene cada 3 semanas y hace 7 que no
    aparece está en riesgo; alguien que viene cada 2 meses y hace 7
    semanas, está normal.
    """
    if visitas == 0:
        return "Sin visitas"
    if tiene_turno_futuro:
        return "Nuevo" if visitas == 1 else "Activo"   # ya reservó: está volviendo
    if visitas == 1:
        return "Nuevo" if dias_desde_ultima <= 45 else "No volvió"
    ritmo = max(float(frecuencia), 14.0)   # piso de 14 días para no exagerar con ritmos muy cortos
    if dias_desde_ultima <= 1.5 * ritmo:
        return "Activo"
    if dias_desde_ultima <= 3 * ritmo:
        return "En riesgo"
    return "Perdido"


def dim_cliente(clientes: pd.DataFrame, turnos: pd.DataFrame, hoy: date, ahora: datetime) -> pd.DataFrame:
    t = turnos.assign(fecha=a_local(turnos["inicio"]).dt.date)
    atendidos = t[t["estado"] == "completado"]

    resumen = atendidos.groupby("cliente_id").agg(
        primera_visita=("fecha", "min"),
        ultima_visita=("fecha", "max"),
        visitas=("turno_id", "count"),
        ingreso_total=("precio_cobrado", "sum"),
    )
    faltazos = t[t["estado"] == "ausente"].groupby("cliente_id").size().rename("faltazos")
    futuros = set(t.loc[(t["estado"] == "reservado") & (pd.to_datetime(t["inicio"], utc=True) > ahora),
                        "cliente_id"])

    c = clientes.set_index("cliente_id").join(resumen).join(faltazos)
    c["visitas"] = c["visitas"].fillna(0).astype(int)
    c["faltazos"] = c["faltazos"].fillna(0).astype(int)
    c["ingreso_total"] = c["ingreso_total"].fillna(0).astype(float)
    # Frecuencia media = (última - primera) / (visitas - 1). Es lo mismo que
    # promediar los días entre cada par de visitas consecutivas.
    span = (pd.to_datetime(c["ultima_visita"]) - pd.to_datetime(c["primera_visita"])).dt.days
    c["frecuencia_media_dias"] = (span / (c["visitas"] - 1)).where(c["visitas"] >= 2).round(1)
    c["dias_desde_ultima"] = (pd.Timestamp(hoy) - pd.to_datetime(c["ultima_visita"])).dt.days.astype("Int64")
    c["tiene_turno_futuro"] = c.index.isin(futuros)
    c["segmento"] = [
        segmentar(v, d, f, fut) for v, d, f, fut in
        zip(c["visitas"], c["dias_desde_ultima"], c["frecuencia_media_dias"], c["tiene_turno_futuro"])
    ]
    c["segmento_orden"] = c["segmento"].map(SEGMENTOS)
    c["fecha_alta"] = a_local(c["creado_en"]).dt.date

    return c.reset_index().rename(columns={"cliente_id": "cliente_key"})[[
        "cliente_key", "nombre", "telefono", "fecha_alta", "primera_visita", "ultima_visita",
        "visitas", "faltazos", "frecuencia_media_dias", "dias_desde_ultima", "ingreso_total",
        "tiene_turno_futuro", "segmento", "segmento_orden",
    ]]


def fact_capacidad(horarios, bloqueos, turnos, barberos, desde: date, hasta: date) -> pd.DataFrame:
    """Minutos disponibles vs. usados por barbero y día.

    disponibles = franjas del horario semanal − minutos bloqueados
    El denominador de la ocupación. Sin descontar los bloqueos, una
    semana de vacaciones aparecería como "semana con 0% de ocupación".
    """
    bloq = [(b, d.to_pydatetime(), h.to_pydatetime()) for b, d, h in
            zip(bloqueos["barbero_id"], a_local(bloqueos["desde"]), a_local(bloqueos["hasta"]))]
    franjas = horarios.groupby(["barbero_id", "dia_semana"])[["hora_desde", "hora_hasta"]] \
        .apply(lambda g: list(zip(g["hora_desde"], g["hora_hasta"]))).to_dict()

    filas = []
    dia = desde
    while dia <= hasta:
        for b in barberos["barbero_key"]:
            minutos = 0
            for h_desde, h_hasta in franjas.get((b, dia.isoweekday()), []):
                ini = datetime.combine(dia, h_desde, TZ)
                fin = datetime.combine(dia, h_hasta, TZ)
                bloqueado = sum(
                    max(0, (min(fin, bh) - max(ini, bd)).total_seconds())
                    for bb, bd, bh in bloq if bb == b
                )
                minutos += int(((fin - ini).total_seconds() - bloqueado) // 60)
            filas.append({"fecha": dia, "barbero_key": b, "minutos_disponibles": minutos})
        dia += timedelta(days=1)
    cap = pd.DataFrame(filas)
    cap["fecha_key"] = fecha_key(cap["fecha"])

    t = turnos[turnos["estado"] != "cancelado"].copy()
    t["fecha_key"] = fecha_key(a_local(t["inicio"]).dt.date)
    t["minutos"] = (pd.to_datetime(t["fin"]) - pd.to_datetime(t["inicio"])).dt.total_seconds() // 60
    t["minutos_atendidos"] = t["minutos"].where(t["estado"] == "completado", 0)
    uso = t.groupby(["fecha_key", "barbero_id"]).agg(
        minutos_reservados=("minutos", "sum"), minutos_atendidos=("minutos_atendidos", "sum"),
    ).reset_index().rename(columns={"barbero_id": "barbero_key"})

    # outer: también entran días "cerrados" donde se cargó un turno manual.
    cap = cap.merge(uso, on=["fecha_key", "barbero_key"], how="outer").fillna(0)
    cap = cap[(cap["minutos_disponibles"] > 0) | (cap["minutos_reservados"] > 0)]
    return cap[["fecha_key", "barbero_key", "minutos_disponibles", "minutos_reservados", "minutos_atendidos"]] \
        .astype(int)


def transformar(datos: dict, ahora: datetime) -> dict[str, pd.DataFrame]:
    hoy = ahora.date()
    turnos = datos["turnos"]
    fechas_turnos = a_local(turnos["inicio"]).dt.date
    desde = fechas_turnos.min() if len(turnos) else hoy
    hasta = max(fechas_turnos.max(), hoy) if len(turnos) else hoy

    return {   # el orden importa: primero dimensiones, después hechos (por las FK)
        "dim_fecha": dim_fecha(desde, hasta),
        "dim_hora": dim_hora(),
        "dim_barbero": datos["barberos"],
        "dim_servicio": datos["servicios"],
        "dim_cliente": dim_cliente(datos["clientes"], turnos, hoy, ahora),
        "dim_estado": dim_estado(),
        "fact_turno": fact_turno(turnos, datos["cancelaciones"]),
        "fact_capacidad_diaria": fact_capacidad(datos["horarios"], datos["bloqueos"], turnos,
                                                datos["barberos"], desde, hasta),
    }


# ======================================================================
#  3. CARGA
# ======================================================================

def validar(tablas: dict[str, pd.DataFrame]) -> None:
    """Chequeos de calidad antes de cargar. Si algo no cierra, el ETL
    falla y Power BI sigue mostrando los datos de ayer (que están bien),
    en vez de mostrar datos rotos."""
    f = tablas["fact_turno"]
    assert f["turno_id"].is_unique, "turno_id duplicado"
    assert (f["precio"] >= 0).all(), "precios negativos"
    assert (f[["completado", "ausente", "cancelado"]].sum(axis=1) <= 1).all(), "estado inconsistente"
    for col, dim, key in [("cliente_key", "dim_cliente", "cliente_key"),
                          ("barbero_key", "dim_barbero", "barbero_key"),
                          ("servicio_key", "dim_servicio", "servicio_key"),
                          ("fecha_key", "dim_fecha", "fecha_key")]:
        huerfanos = set(f[col]) - set(tablas[dim][key])
        assert not huerfanos, f"{col} sin dimensión: {sorted(huerfanos)[:5]}"


def cargar(conn, tablas: dict[str, pd.DataFrame]) -> None:
    conn.connection.driver_connection.execute(SQL_ESQUEMA.read_text(encoding="utf-8"))
    nombres = ", ".join(f"analytics.{n}" for n in tablas)
    conn.execute(text(f"TRUNCATE {nombres}"))
    for nombre, df in tablas.items():
        df.to_sql(nombre, conn, schema="analytics", if_exists="append", index=False,
                  method="multi", chunksize=1000)


def correr() -> dict[str, int]:
    ahora = datetime.now(TZ)
    t0 = reloj.perf_counter()
    with engine.begin() as conn:
        conn.connection.driver_connection.execute(SQL_ESQUEMA.read_text(encoding="utf-8"))
        id_ejecucion = conn.execute(text(
            "INSERT INTO analytics.etl_ejecucion (inicio, estado) VALUES (:i, 'corriendo') RETURNING id"
        ), {"i": ahora}).scalar_one()

    try:
        # Toda la carga en UNA transacción: Power BI ve los datos viejos o
        # los nuevos completos, nunca una mezcla a medio cargar.
        with engine.begin() as conn:
            tablas = transformar(extraer(conn), ahora)
            validar(tablas)
            cargar(conn, tablas)
        filas = {n: len(df) for n, df in tablas.items()}
        estado, error = "ok", None
    except Exception as e:
        filas, estado, error = None, "error", repr(e)
        raise
    finally:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE analytics.etl_ejecucion
                SET fin = now(), estado = :e, filas = CAST(:f AS jsonb), error = :err WHERE id = :id
            """), {"e": estado, "f": json.dumps(filas), "err": error, "id": id_ejecucion})

    print(f"ETL ok en {reloj.perf_counter() - t0:.1f} s")
    for n, c in filas.items():
        print(f"  analytics.{n:<22} {c:>6} filas")
    return filas


if __name__ == "__main__":
    correr()
