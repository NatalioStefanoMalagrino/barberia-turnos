# 5. Tablero en Power BI

Power BI Desktop solo funciona en **Windows**.

## 1. Conectar

1. **Obtener datos → Base de datos PostgreSQL**.
2. **Servidor:** `localhost:5432` (local) o el host de Neon (ver [06-deploy.md](06-deploy.md)). **Base de datos:** `barberia` en local, `neondb` en Neon.
3. **Modo:** **Importar** (no DirectQuery). Los datos se actualizan una vez por noche, así que no hace falta consultar la base en vivo, e Importar es mucho más rápido.
4. Credenciales de **base de datos**: usuario y contraseña de PostgreSQL.
5. Marcar solo las tablas del esquema `analytics`:
   `dim_fecha`, `dim_hora`, `dim_barbero`, `dim_servicio`, `dim_cliente`, `dim_estado`, `fact_turno`, `fact_capacidad_diaria` y la vista `v_clientes_para_contactar`.

> Si Power BI pide instalar un conector o da error de certificado, seguí el aviso que muestra. Neon exige conexión cifrada (SSL).

Nunca conectes Power BI a las tablas del esquema `public` (las de la web). El modelo analítico existe justamente para eso.

## 2. Relaciones (vista Modelo)

Todas de **uno a varios**, con filtro en **una sola dirección** (de la dimensión al hecho):

| Desde (1) | Hacia (*) |
|---|---|
| `dim_fecha[fecha_key]` | `fact_turno[fecha_key]` y `fact_capacidad_diaria[fecha_key]` |
| `dim_barbero[barbero_key]` | `fact_turno[barbero_key]` y `fact_capacidad_diaria[barbero_key]` |
| `dim_hora[hora]` | `fact_turno[hora]` |
| `dim_servicio[servicio_key]` | `fact_turno[servicio_key]` |
| `dim_cliente[cliente_key]` | `fact_turno[cliente_key]` |
| `dim_estado[estado]` | `fact_turno[estado]` |

Como `dim_fecha` y `dim_barbero` filtran las dos tablas de hechos, un segmentador de mes o de barbero afecta ingresos y ocupación a la vez. Es un modelo de **constelación**: dos hechos que comparten dimensiones.

## 3. Ajustes de orden (si no, los meses salen en orden alfabético)

- `dim_fecha`: **Marcar como tabla de fechas** (columna `fecha`).
- `dim_fecha[mes_nombre]` → Ordenar por columna → `mes`.
- `dim_fecha[dia_semana]` → Ordenar por columna → `dia_semana_num`.
- `dim_cliente[segmento]` → Ordenar por columna → `segmento_orden`.
- Ocultar las columnas `_key` y los números de orden (clic derecho → Ocultar en la vista de informe).

## 4. Medidas (DAX)

Creá una tabla vacía llamada `Medidas` para tenerlas juntas.

```dax
Ingresos = SUM ( fact_turno[ingreso] )

Turnos atendidos = SUM ( fact_turno[completado] )

Ticket promedio = DIVIDE ( [Ingresos], [Turnos atendidos] )

Faltazos = SUM ( fact_turno[ausente] )

Tasa de faltazos =
DIVIDE ( [Faltazos], [Turnos atendidos] + [Faltazos] )

Plata perdida por faltazos = SUM ( fact_turno[ingreso_perdido] )

Ocupación =
DIVIDE (
    SUM ( fact_capacidad_diaria[minutos_reservados] ),
    SUM ( fact_capacidad_diaria[minutos_disponibles] )
)

Clientes en riesgo =
CALCULATE ( COUNTROWS ( dim_cliente ), dim_cliente[segmento] = "En riesgo" )

Clientes nuevos =
CALCULATE (
    SUM ( fact_turno[completado] ),
    fact_turno[es_primera_visita] = TRUE ()
)

% reservas online =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_turno ), fact_turno[origen] = "web" ),
    COUNTROWS ( fact_turno )
)

Ingresos mes anterior =
CALCULATE ( [Ingresos], DATEADD ( dim_fecha[fecha], -1, MONTH ) )

Variación vs mes anterior =
DIVIDE ( [Ingresos] - [Ingresos mes anterior], [Ingresos mes anterior] )
```

Formato: `Tasa de faltazos`, `Ocupación`, `% reservas online` y `Variación` como **porcentaje**; `Ingresos`, `Ticket` y `Plata perdida` como **moneda sin decimales**.

**Por qué medidas y no columnas calculadas:** una medida se calcula según los filtros activos (mes, barbero, servicio). `Tasa de faltazos` tiene que dar distinto para Mati en julio que para toda la barbería en el año. Una columna calculada es un valor fijo por fila y no se adapta.

**Por qué `DIVIDE` y no `/`:** si el denominador es 0 (un día sin turnos), `DIVIDE` devuelve vacío en vez de error.

## 5. Páginas sugeridas

Pensadas para responder preguntas del dueño, no para mostrar todo lo que hay.

### Página 1: "¿Cómo viene el negocio?"
- Tarjetas: **Ingresos**, **Variación vs mes anterior**, **Turnos atendidos**, **Ticket promedio**, **Ocupación**.
- Líneas: Ingresos por `anio_mes`.
- Barras: Ocupación por `dia_semana`.
- Segmentadores: mes, barbero.

### Página 2: "¿Dónde tengo huecos?"
- Barras: Ocupación por `dia_semana` y por barbero.
- Matriz: `dia_semana` (filas) × `franja` (columnas), valor = cantidad de turnos atendidos, con formato condicional de color de fondo (mapa de calor).

### Página 3: "¿Qué clientes estoy perdiendo?"
- Barras: cantidad de clientes por `segmento`.
- Tabla: `v_clientes_para_contactar` (nombre, teléfono, última visita, días sin venir, cuánto gastó).
- Líneas: Clientes nuevos por mes.

### Página 4: "¿Cuánto me cuestan los faltazos?"
- Tarjetas: **Tasa de faltazos**, **Plata perdida por faltazos**.
- Barras: Tasa de faltazos por `es_primera_visita`.
- Barras: Tasa de faltazos por día de la semana.

## 6. Qué muestran los datos simulados

Estos son los hallazgos que deberían aparecer (los números exactos cambian según el día en que se corre el generador):

- **Los martes tienen menos de la mitad de ocupación que los sábados.** Una promo de martes puede llenar horarios que hoy se pierden.
- **Los clientes nuevos faltan el doble que los habituales.** Pedir seña solo en la primera visita ataca el problema sin molestar a los de siempre.
- **Hay decenas de clientes habituales "en riesgo"**, con nombre y teléfono. Un WhatsApp esta semana puede recuperar una parte.

Así se presenta en el pitch: tres hallazgos y tres acciones, no un tablero lleno de gráficos.

## 7. Entregarlo al cliente

Compartir el tablero requiere licencia Pro para quien publica y para cada persona que lo mira. Para una barbería conviene:

1. Actualizar el tablero (Inicio → **Actualizar**) a principio de mes.
2. **Archivo → Exportar → Exportar a PDF**.
3. Mandarlo con 3 o 4 recomendaciones concretas, o repasarlo en una charla de 15 minutos.
