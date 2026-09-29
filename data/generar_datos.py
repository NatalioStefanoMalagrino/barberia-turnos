"""Generador de datos de prueba realistas.

Sirve para dos cosas:
  1. Tener algo que mostrar en el pitch: un tablero con 6 meses de
     historia "creíble" antes de que la barbería use el sistema.
  2. Probar el ETL y el modelo estrella con volumen y con los casos raros
     (faltazos, cancelaciones, clientes que dejan de venir, aumentos).

Todo es FALSO (nombres y teléfonos inventados con Faker). Los patrones
sí están pensados para parecerse a una barbería real:
  * viernes, sábados y la franja de 17 a 20 h se llenan primero;
  * clientes habituales que vuelven cada ~3-5 semanas, ocasionales cada
    ~2-3 meses, y gente que viene una sola vez;
  * algunos habituales "se pierden" en algún momento (churn);
  * ~8% de faltazos (más en clientes nuevos) y ~7% de cancelaciones;
  * aumentos de precio cada 2 meses (inflación).

Uso (⚠ BORRA turnos, clientes y bloqueos de la base configurada):
    python -m data.generar_datos --si-borrar-todo
"""
import argparse
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from faker import Faker
from sqlalchemy import MetaData, Table, insert, text

from app.config import TZ
from app.db import engine

SEMILLA = 42          # misma semilla = mismos datos: resultados reproducibles
MESES_HISTORIA = 6
DIAS_FUTURO = 14      # turnos ya reservados para las próximas 2 semanas
N_CLIENTES = 1750
PASO = 15

random.seed(SEMILLA)
fake = Faker("es_AR")
Faker.seed(SEMILLA)


# ------------------------------------------------------------ perfiles

@dataclass
class Cliente:
    id: int
    tipo: str                    # habitual | ocasional | una_vez
    frecuencia: int              # días entre visitas
    alta: date                   # primera visita "deseada"
    baja: date | None            # desde cuándo deja de venir (churn)
    barbero_pref: int | None
    servicio_pref: int
    prefiere_sabado: bool


def elegir(opciones: dict):
    return random.choices(list(opciones), weights=list(opciones.values()))[0]


def crear_clientes(servicios: dict, barberos: list[int], hoy: date, desde: date) -> list[Cliente]:
    """Arma la cartera de clientes con distintos comportamientos."""
    peso_servicio = {"Corte": 30, "Fade": 30, "Corte + barba": 28, "Barba": 8, "Diseño / cejas": 4}
    ids_por_nombre = {s["nombre"]: s["id"] for s in servicios.values()}
    clientes = []
    dias_periodo = (hoy - desde).days

    for i in range(1, N_CLIENTES + 1):
        tipo = elegir({"habitual": 30, "ocasional": 35, "una_vez": 35})
        if tipo == "habitual":
            frecuencia = max(18, int(random.gauss(28, 5)))
        elif tipo == "ocasional":
            frecuencia = random.randint(50, 90)
        else:
            frecuencia = 10_000
        # 55% ya eran clientes antes del período: su primera visita cae en
        # algún punto de su ciclo. El resto son clientes nuevos que van
        # llegando a lo largo de los 6 meses.
        if random.random() < 0.55:
            alta = desde + timedelta(days=random.randint(0, min(frecuencia, 60)))
        else:
            alta = desde + timedelta(days=random.randint(0, dias_periodo + DIAS_FUTURO))
        baja = None
        if tipo != "una_vez" and random.random() < 0.22:
            baja = alta + timedelta(days=random.randint(frecuencia, max(frecuencia + 1, dias_periodo)))
        clientes.append(Cliente(
            id=i, tipo=tipo, frecuencia=frecuencia, alta=alta, baja=baja,
            barbero_pref=random.choice(barberos) if tipo != "una_vez" and random.random() < 0.8 else None,
            servicio_pref=ids_por_nombre[elegir(peso_servicio)],
            prefiere_sabado=random.random() < 0.35,
        ))
    return clientes


# ----------------------------------------------------- agenda en memoria

def precio_historico(precio_actual: float, fecha: date, hoy: date) -> float:
    """Aumento de ~7% cada 60 días hacia atrás, redondeado a $500."""
    escalones = max(0, (hoy - fecha).days) // 60
    return round(precio_actual / (1.07 ** escalones) / 500) * 500


def peso_hora(h: time, sabado: bool) -> float:
    """Qué tan buscada es cada hora: la salida del trabajo y el sábado a la
    mañana se llenan primero; el mediodía de semana, último."""
    if sabado:
        return 3.0 if h < time(13) else 1.8
    if time(17) <= h < time(20):
        return 3.2
    if h < time(12):
        return 1.0
    return 1.4


# Qué tan buscado es cada día (ISO: 2 = martes ... 6 = sábado).
PESO_DIA = {2: 0.75, 3: 0.85, 4: 1.0, 5: 1.45, 6: 1.7}


def acomodar_dia(dia: date, prefiere_sabado: bool) -> date:
    """La gente no viene exactamente cada N días: corre la visita un par de
    días hacia el día que le queda cómodo (viernes y sábado ganan)."""
    if prefiere_sabado:
        return dia + timedelta(days=(6 - dia.isoweekday()) % 7)
    opciones = [dia + timedelta(days=k) for k in range(-2, 3)]
    opciones = [d for d in opciones if d.isoweekday() in PESO_DIA]
    return random.choices(opciones, weights=[PESO_DIA[d.isoweekday()] for d in opciones])[0]


def main(confirmado: bool) -> None:
    if not confirmado:
        raise SystemExit("Este script BORRA turnos y clientes. Correlo con --si-borrar-todo.")

    ahora = datetime.now(TZ)
    hoy = ahora.date()
    desde = hoy - timedelta(days=30 * MESES_HISTORIA)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE turno_evento, turno, cliente, bloqueo RESTART IDENTITY CASCADE"))
        servicios = {r["id"]: dict(r) for r in conn.execute(
            text("SELECT id, nombre, duracion_min, precio FROM servicio WHERE activo")).mappings()}
        barberos = [r[0] for r in conn.execute(text("SELECT id FROM barbero WHERE activo ORDER BY id"))]
        franjas = defaultdict(list)          # (barbero, dia_semana) -> [(desde, hasta)]
        for r in conn.execute(text("SELECT barbero_id, dia_semana, hora_desde, hora_hasta FROM horario_barbero")):
            franjas[(r.barbero_id, r.dia_semana)].append((r.hora_desde, r.hora_hasta))

        # Vacaciones de un barbero en el pasado: el tablero de ocupación
        # tiene que descontarlas de la capacidad (si no, parecería un bajón).
        vac_ini = desde + timedelta(days=75)
        bloqueos = [(barberos[-1], datetime.combine(vac_ini, time(0), TZ),
                     datetime.combine(vac_ini + timedelta(days=7), time(0), TZ), "Vacaciones")]
        conn.execute(text("INSERT INTO bloqueo (barbero_id, desde, hasta, motivo) VALUES (:b, :d, :h, :m)"),
                     [{"b": b, "d": d, "h": h, "m": m} for b, d, h, m in bloqueos])

        clientes = crear_clientes(servicios, barberos, hoy, desde)
        telefonos = random.sample(range(10_000_000, 99_999_999), N_CLIENTES)
        conn.execute(text("""
            INSERT INTO cliente (id, nombre, telefono, email, creado_en) VALUES (:id, :n, :t, :e, :c)
        """), [{
            "id": c.id, "n": f"{fake.first_name()} {fake.last_name()}", "t": f"11{telefonos[c.id - 1]}",
            "e": fake.email() if random.random() < 0.3 else None,
            "c": datetime.combine(c.alta, time(9), TZ),
        } for c in clientes])
        conn.execute(text("SELECT setval('cliente_id_seq', (SELECT max(id) FROM cliente))"))

        # ------------------------------------------------ ubicar las visitas
        ocupado = defaultdict(list)   # (barbero, fecha) -> [(ini, fin)]

        def libre(b, ini, fin):
            return all(not (ini < o_fin and o_ini < fin) for o_ini, o_fin in ocupado[(b, ini.date())]) and \
                all(not (ini < bh and bd < fin) for bb, bd, bh, _ in bloqueos if bb == b)

        def ubicar(c: Cliente, dia: date):
            """Busca lugar cerca del día deseado (±2 días); si no hay, la visita se pierde."""
            servicio = servicios[c.servicio_pref if random.random() < 0.85 else random.choice(list(servicios))]
            dur = timedelta(minutes=servicio["duracion_min"])
            for corrimiento in (0, -1, 1, -2, 2):     # busca alrededor del día deseado
                d = dia + timedelta(days=corrimiento)
                if d < desde or d > hoy + timedelta(days=DIAS_FUTURO):
                    continue
                barberos_orden = ([c.barbero_pref] if c.barbero_pref else []) + \
                    random.sample(barberos, len(barberos))
                for b in dict.fromkeys(barberos_orden):
                    candidatos = []
                    for f_desde, f_hasta in franjas.get((b, d.isoweekday()), []):
                        ini = datetime.combine(d, f_desde, TZ)
                        while ini + dur <= datetime.combine(d, f_hasta, TZ):
                            if libre(b, ini, ini + dur):
                                candidatos.append(ini)
                            ini += timedelta(minutes=PASO)
                    if candidatos:
                        pesos = [peso_hora(x.time(), d.isoweekday() == 6) for x in candidatos]
                        ini = random.choices(candidatos, weights=pesos)[0]
                        ocupado[(b, d)].append((ini, ini + dur))
                        return b, servicio, ini, ini + dur
                    if c.barbero_pref == b and random.random() < 0.5:
                        break   # la mitad de los fieles prefiere cambiar de día antes que de barbero
            return None

        visitas = []
        for c in clientes:
            dia = c.alta
            n = 0
            while dia <= hoy + timedelta(days=DIAS_FUTURO) and (c.baja is None or dia < c.baja):
                dia = acomodar_dia(dia, c.prefiere_sabado)
                lugar = ubicar(c, dia)
                if lugar:
                    visitas.append((c, n, *lugar))
                    n += 1
                if c.tipo == "una_vez":
                    break
                dia += timedelta(days=max(10, int(random.gauss(c.frecuencia, c.frecuencia * 0.15))))

        # --------------------------------- estados, anticipación y precios
        filas, cambios = [], []
        for c, n_visita, b, servicio, ini, fin in visitas:
            manual = random.random() < 0.25
            if manual and random.random() < 0.4:
                creado = ini - timedelta(minutes=5)                      # entró sin turno
            else:
                horas_antes = min(24 * 14, max(1.5, random.lognormvariate(math.log(40), 1.0)))
                creado = ini - timedelta(hours=horas_antes)
            if creado > ahora:
                continue    # todavía no "sucedió" la reserva
            pasado = fin <= ahora
            p_cancela = 0.07
            p_falta = 0.12 if n_visita == 0 else 0.06
            if (ini - creado) > timedelta(days=5):
                p_falta += 0.04          # reservas muy anticipadas se olvidan más
            azar = random.random()
            if azar < p_cancela:
                momento = ini - timedelta(hours=random.uniform(1, max(1.5, (ini - creado).total_seconds() / 3600)))
                estado, ts = ("cancelado", momento) if momento <= ahora else ("reservado", None)
            elif pasado and azar < p_cancela + p_falta:
                estado, ts = "ausente", fin + timedelta(minutes=random.randint(5, 90))
            elif pasado:
                estado, ts = "completado", fin + timedelta(minutes=random.randint(1, 60))
            else:
                estado, ts = "reservado", None
            filas.append({
                "cliente_id": c.id, "barbero_id": b, "servicio_id": servicio["id"],
                "inicio": ini, "fin": fin, "estado": "reservado",
                "precio_cobrado": precio_historico(float(servicio["precio"]), ini.date(), hoy),
                "origen": "manual" if manual else "web", "creado_en": creado, "actualizado_en": creado,
            })
            cambios.append((estado, ts, "cliente" if estado == "cancelado" and not manual else "barbero"))

        # Insertamos todo como 'reservado' (el trigger registra la creación
        # con la fecha creado_en) y después aplicamos los cambios de estado
        # con su fecha real, así turno_evento queda como si hubiera pasado
        # de verdad a lo largo de los 6 meses.
        turno_t = Table("turno", MetaData(), autoload_with=conn)
        ids = conn.execute(insert(turno_t).returning(turno_t.c.id, sort_by_parameter_order=True),
                           filas).scalars().all()

        for actor in ("barbero", "cliente"):
            conn.execute(text("SELECT set_config('app.actor', :a, true)"), {"a": actor})
            lote = [{"id": i, "e": e, "ts": ts} for i, (e, ts, a) in zip(ids, cambios)
                    if e != "reservado" and a == actor]
            if lote:
                conn.execute(text("UPDATE turno SET estado = :e, actualizado_en = :ts WHERE id = :id"), lote)

        # En el sistema real un cliente se crea al reservar: no puede haber
        # clientes sin ningún turno. Borramos los que no llegaron a tener.
        conn.execute(text("DELETE FROM cliente c WHERE NOT EXISTS (SELECT 1 FROM turno t WHERE t.cliente_id = c.id)"))
        n_clientes = conn.execute(text("SELECT count(*) FROM cliente")).scalar()
        resumen = conn.execute(text("SELECT estado, count(*) FROM turno GROUP BY estado ORDER BY 2 DESC")).all()

    print(f"Clientes: {n_clientes} · Turnos: {len(filas)}")
    for estado, n in resumen:
        print(f"  {estado:<11} {n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--si-borrar-todo", action="store_true", help="Confirma que se puede borrar la base")
    main(ap.parse_args().si_borrar_todo)
