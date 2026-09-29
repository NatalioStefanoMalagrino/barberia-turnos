# 4. Ingeniería de datos: datos simulados, ETL y modelo estrella

## El flujo

```
 Sistema de turnos (esquema public)          Esquema analytics                 Power BI
 ─────────────────────────────────           ─────────────────                 ────────
 turno, turno_evento, cliente,     ──ETL──▶  dim_fecha, dim_hora,     ──────▶  Tablero
 barbero, servicio, horario,     (cada noche) dim_barbero, dim_servicio,         (Import)
 bloqueo                                      dim_cliente, dim_estado,
                                              fact_turno,
                                              fact_capacidad_diaria
```

## Paso 1: datos simulados (`data/generar_datos.py`)

Antes de que la barbería use el sistema no hay datos, y para el pitch hace falta un tablero con algo creíble. El generador arma **6 meses de historia** con patrones parecidos a los reales:

- Viernes y sábados, y la franja de 17 a 20 h, se llenan primero. Si no hay lugar, el cliente se corre un día antes o después.
- Tres tipos de cliente: habituales (vuelven cada 3 a 5 semanas), ocasionales (cada 2 o 3 meses) y de una sola visita.
- Algunos habituales **dejan de venir** en algún momento (churn): son los que después aparecen "en riesgo" o "perdidos".
- Faltazos: alrededor de 7% en clientes conocidos y 14% en primeras visitas, más en reservas hechas con mucha anticipación.
- Cancelaciones: alrededor de 7%, avisando entre 1 hora y varios días antes.
- Aumento de precios del 7% cada 2 meses.
- Una semana de vacaciones de un barbero.

Usa una semilla fija: dos corridas el mismo día dan los mismos datos. Inserta los turnos como `reservado` y después les cambia el estado con fecha histórica, así el trigger llena `turno_evento` como si todo hubiera pasado de verdad.

```bash
python -m data.generar_datos --si-borrar-todo    # ⚠ borra turnos y clientes
```

## Paso 2: el modelo estrella (`data/analytics_schema.sql`)

Mismo enfoque que en la materia: hechos en el centro, dimensiones alrededor.

### Por qué dos tablas de hechos

| Tabla | Grano | Para qué |
|---|---|---|
| `fact_turno` | 1 turno | Ingresos, faltazos, cancelaciones, anticipación, primeras visitas |
| `fact_capacidad_diaria` | 1 barbero × 1 día | **Ocupación** |

La ocupación no se puede sacar solo de los turnos: hace falta el **denominador**, los minutos que había disponibles. Y un día sin ningún turno no aparece en `fact_turno`, pero sí existe (con 0% de ocupación). Por eso la capacidad es un hecho aparte, con otro grano. Mezclar granos en una sola tabla es uno de los errores más comunes en modelado dimensional.

### Decisiones de diseño

- **`fecha_key` como entero `20261006`**: los joins por entero son más rápidos que por fecha, y es el estándar en data warehousing.
- **`dim_fecha` tiene todos los días del rango**, haya turnos o no. Si faltaran los días vacíos, Power BI no los mostraría y un bache pasaría desapercibido.
- **Banderas 0/1 (`completado`, `ausente`, `cancelado`)**: en Power BI se suman directamente, sin filtros. `SUM(ausente)` es la cantidad de faltazos.
- **`ingreso` e `ingreso_perdido` ya calculados**: el ETL resuelve la lógica una sola vez y Power BI solo suma.
- **Todo en hora de Buenos Aires**: la base guarda en UTC. Un turno de las 22 h UTC es de las 19 h acá, que es otra franja horaria. La conversión se hace en el ETL.
- **`dim_cliente` es una foto actual (SCD tipo 1)**: se recalcula entera cada noche. Para ver cómo cambió el segmento de un cliente en el tiempo haría falta SCD tipo 2 (guardar versiones con fechas de vigencia). Para esta etapa no hace falta.

## Paso 3: el ETL (`data/etl.py`)

```bash
python -m data.etl
```

1. **Extraer** solo las columnas necesarias (nunca `SELECT *`: si se agrega una columna al sistema, el ETL no se rompe).
2. **Transformar** con pandas: dimensiones, hechos y atributos calculados.
3. **Validar**: IDs únicos, precios no negativos, ningún hecho sin su dimensión. Si algo falla, el ETL se corta y Power BI sigue mostrando los datos de ayer, que están bien, en vez de datos rotos.
4. **Cargar** todo en **una sola transacción**: Power BI ve o los datos viejos o los nuevos completos, nunca una mezcla a medio cargar.
5. **Registrar** la corrida en `analytics.etl_ejecucion` (cuándo, cuántas filas, si falló y por qué).

**Carga completa (full refresh), no incremental.** Con miles de filas tarda 3 segundos. Es la opción más simple y se corrige sola: si un turno de hace 2 semanas se marca tarde como ausente, la próxima corrida lo refleja. Cuando haya muchas barberías o millones de filas, se pasa a incremental, procesando solo lo que cambió desde la última corrida (`turno.actualizado_en` está para eso).

Se programa para todas las noches con GitHub Actions (`.github/workflows/etl.yml`).

## La métrica estrella: segmentación de clientes

Está en `segmentar()` dentro de `etl.py`. La clave es **comparar a cada cliente contra su propio ritmo**, no contra un promedio general:

| Segmento | Regla |
|---|---|
| Nuevo | 1 visita, hace 45 días o menos |
| Activo | Vino dentro de 1,5 veces su frecuencia habitual, o ya tiene un turno reservado |
| **En riesgo** | Lleva entre 1,5 y 3 veces su frecuencia sin venir |
| Perdido | Más de 3 veces su frecuencia |
| No volvió | 1 visita, hace más de 45 días |
| Sin visitas | Solo tuvo turnos cancelados, faltazos o turnos futuros |

Ejemplo: alguien que viene cada 3 semanas y hace 7 que no aparece está **en riesgo**. Alguien que viene cada 2 meses y hace 7 semanas que no aparece está **normal**. Un promedio general los trataría igual.

La vista `analytics.v_clientes_para_contactar` devuelve la lista lista para usar: clientes en riesgo sin turno reservado, ordenados por cuánto gastaron. Es lo que el dueño puede accionar el mismo día, mandando un WhatsApp.

Los umbrales (1,5, 3 y 45 días) son una primera versión razonable. Con datos reales se pueden ajustar viendo cuántos "en riesgo" efectivamente vuelven.
