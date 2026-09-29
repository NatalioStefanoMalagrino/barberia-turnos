-- =====================================================================
--  Modelo estrella para Power BI (esquema "analytics")
-- =====================================================================
--  Vive en la MISMA base que el sistema de turnos pero en otro esquema.
--  Las tablas de acá las llena el ETL (data/etl.py) todas las noches;
--  la web nunca escribe en ellas.
--
--  ¿Por qué separarlo del esquema de turnos?
--   * Las consultas pesadas de Power BI no compiten con las reservas.
--   * El modelo transaccional está pensado para ESCRIBIR sin errores
--     (normalizado, con constraints). El analítico está pensado para
--     LEER y agregar rápido (desnormalizado, con atributos ya calculados).
--   * Si mañana cambiamos algo del sistema, el tablero no se rompe: solo
--     se ajusta el ETL.
--
--  Dos tablas de hechos:
--   * fact_turno              grano = 1 turno
--   * fact_capacidad_diaria   grano = 1 barbero x 1 día
--  La segunda existe porque la OCUPACIÓN no se puede sacar solo de los
--  turnos: necesitás saber cuántos minutos había disponibles (horarios
--  menos francos y vacaciones), incluso en los días sin ningún turno.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS analytics;

-- ------------------------------------------------------------ dimensiones

CREATE TABLE IF NOT EXISTS analytics.dim_fecha (
    fecha_key         INTEGER PRIMARY KEY,        -- 20261006 (entero: joins más rápidos)
    fecha             DATE    NOT NULL UNIQUE,
    anio              SMALLINT NOT NULL,
    mes               SMALLINT NOT NULL,
    mes_nombre        TEXT    NOT NULL,           -- 'Octubre'
    anio_mes          TEXT    NOT NULL,           -- '2026-10' (para ordenar y agrupar)
    semana_iso        SMALLINT NOT NULL,
    dia_semana_num    SMALLINT NOT NULL,          -- 1 = lunes ... 7 = domingo
    dia_semana        TEXT    NOT NULL,           -- 'Martes'
    es_fin_de_semana  BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_hora (
    hora    SMALLINT PRIMARY KEY,                 -- 0 a 23
    franja  TEXT NOT NULL                         -- Mañana / Mediodía / Tarde / Salida del trabajo / Noche
);

CREATE TABLE IF NOT EXISTS analytics.dim_barbero (
    barbero_key  INTEGER PRIMARY KEY,             -- = barbero.id
    nombre       TEXT    NOT NULL,
    activo       BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_servicio (
    servicio_key   INTEGER PRIMARY KEY,           -- = servicio.id
    nombre         TEXT    NOT NULL,
    duracion_min   INTEGER NOT NULL,
    precio_actual  NUMERIC(12,2) NOT NULL
);

-- Foto del cliente al momento de correr el ETL (se recalcula entera
-- cada noche). El segmento es lo más valioso de todo el modelo.
CREATE TABLE IF NOT EXISTS analytics.dim_cliente (
    cliente_key             INTEGER PRIMARY KEY,  -- = cliente.id
    nombre                  TEXT    NOT NULL,
    telefono                TEXT    NOT NULL,     -- para poder contactar a los "en riesgo"
    fecha_alta              DATE    NOT NULL,
    primera_visita          DATE,
    ultima_visita           DATE,
    visitas                 INTEGER NOT NULL,     -- turnos completados
    faltazos                INTEGER NOT NULL,
    frecuencia_media_dias   NUMERIC(6,1),         -- promedio de días entre visitas (≥ 2 visitas)
    dias_desde_ultima       INTEGER,
    ingreso_total           NUMERIC(14,2) NOT NULL,
    tiene_turno_futuro      BOOLEAN NOT NULL,
    segmento                TEXT    NOT NULL,     -- ver data/etl.py: segmentar()
    segmento_orden          SMALLINT NOT NULL     -- para ordenar el segmento en Power BI
);

CREATE TABLE IF NOT EXISTS analytics.dim_estado (
    estado          TEXT PRIMARY KEY,
    descripcion     TEXT NOT NULL,
    ocupa_agenda    BOOLEAN NOT NULL              -- ¿ese turno usó la silla? (ausente = sí, se perdió)
);

-- ------------------------------------------------------------------ hechos

CREATE TABLE IF NOT EXISTS analytics.fact_turno (
    turno_id                         INTEGER PRIMARY KEY,
    fecha_key                        INTEGER NOT NULL REFERENCES analytics.dim_fecha,
    hora                             SMALLINT NOT NULL REFERENCES analytics.dim_hora,
    barbero_key                      INTEGER NOT NULL REFERENCES analytics.dim_barbero,
    servicio_key                     INTEGER NOT NULL REFERENCES analytics.dim_servicio,
    cliente_key                      INTEGER NOT NULL REFERENCES analytics.dim_cliente,
    estado                           TEXT    NOT NULL REFERENCES analytics.dim_estado,
    origen                           TEXT    NOT NULL,            -- web / manual
    -- medidas
    precio                           NUMERIC(12,2) NOT NULL,      -- precio del momento
    ingreso                          NUMERIC(12,2) NOT NULL,      -- solo si se completó
    ingreso_perdido                  NUMERIC(12,2) NOT NULL,      -- faltazos
    duracion_min                     INTEGER NOT NULL,
    anticipacion_horas               NUMERIC(8,1) NOT NULL,       -- cuánto antes reservó
    cancelacion_anticipacion_horas   NUMERIC(8,1),                -- cuánto antes canceló
    es_primera_visita                BOOLEAN NOT NULL,
    completado                       SMALLINT NOT NULL,           -- 0/1: sumables en Power BI
    ausente                          SMALLINT NOT NULL,
    cancelado                        SMALLINT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.fact_capacidad_diaria (
    fecha_key            INTEGER NOT NULL REFERENCES analytics.dim_fecha,
    barbero_key          INTEGER NOT NULL REFERENCES analytics.dim_barbero,
    minutos_disponibles  INTEGER NOT NULL,        -- horario del día - bloqueos
    minutos_reservados   INTEGER NOT NULL,        -- completados + ausentes + pendientes
    minutos_atendidos    INTEGER NOT NULL,        -- solo completados
    PRIMARY KEY (fecha_key, barbero_key)
);

-- Registro de cada corrida del ETL: si una noche falla, se ve acá.
CREATE TABLE IF NOT EXISTS analytics.etl_ejecucion (
    id          SERIAL PRIMARY KEY,
    inicio      TIMESTAMPTZ NOT NULL,
    fin         TIMESTAMPTZ,
    estado      TEXT NOT NULL,                    -- ok / error
    filas       JSONB,
    error       TEXT
);

-- Vista lista para usar: a quién escribirle esta semana.
CREATE OR REPLACE VIEW analytics.v_clientes_para_contactar AS
SELECT nombre, telefono, segmento, visitas, ultima_visita, dias_desde_ultima,
       frecuencia_media_dias, ingreso_total
FROM analytics.dim_cliente
WHERE segmento = 'En riesgo' AND NOT tiene_turno_futuro
ORDER BY ingreso_total DESC;
