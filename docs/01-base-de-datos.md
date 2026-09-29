# 1. Base de datos (modelo transaccional)

Archivo: [`db/01_schema.sql`](../db/01_schema.sql). Está comentado línea por línea; acá va el razonamiento general.

## Por qué se diseñó primero la base

Todo lo demás (la web, el panel, el ETL y Power BI) lee o escribe estas tablas. Un error acá se arrastra a todo. Además, la parte de datos solo puede medir lo que el sistema registra: si hoy no guardamos cuándo se canceló un turno, mañana ningún dashboard puede calcularlo.

La pregunta que guió el diseño fue: **¿qué va a querer saber el dueño dentro de 6 meses?** Y de ahí, hacia atrás: qué hay que guardar hoy.

## Tablas

| Tabla | Qué guarda | Decisión clave |
|---|---|---|
| `barbero` | Quién atiende | `activo` en vez de borrar: si un barbero se va, sus turnos históricos siguen apuntando a él |
| `servicio` | Qué se ofrece | `precio` es el **vigente** |
| `horario_barbero` | Franjas semanales | Varias filas por día permiten cortar al mediodía |
| `bloqueo` | Francos, vacaciones, trámites | Se descuentan de la capacidad en el ETL |
| `cliente` | Quién reserva | Se identifica por **teléfono**, sin usuario ni contraseña |
| `turno` | Cada reserva | Guarda `precio_cobrado`, `estado`, `origen`, `creado_en` |
| `turno_evento` | Historial de estados | Lo escribe un **trigger**, no la app |
| `usuario_panel` | Login de barberos y dueño | Contraseña hasheada con PBKDF2 |

## Las 5 decisiones importantes

### 1. La regla anti-superposición está en la base

```sql
CONSTRAINT turno_sin_superposicion EXCLUDE USING gist (
    barbero_id WITH =,
    tstzrange(inicio, fin, '[)') WITH &&
) WHERE (estado <> 'cancelado')
```

Se lee: "no puede haber dos filas con el mismo `barbero_id` (`=`) cuyos intervalos de tiempo se superpongan (`&&`), salvo que estén canceladas".

**Por qué no alcanza con validarlo en Python:** si dos clientes reservan el mismo horario al mismo tiempo, las dos requests chequean "¿está libre?", las dos ven que sí, y las dos insertan. Es una *condición de carrera*. La base es el único lugar que ve las dos transacciones a la vez, y por eso es la única que puede frenar una.

`'[)'` significa intervalo semiabierto: incluye el inicio y excluye el fin. Así un turno de 10:00 a 10:30 y otro de 10:30 a 11:00 no se pisan.

### 2. El precio se guarda en el turno

`servicio.precio` es el precio de hoy. Si los ingresos de abril se calcularan con el precio de hoy, con inflación saldrían inflados. `turno.precio_cobrado` congela el precio del momento. Es el mismo principio que en un data warehouse: **el hecho guarda el valor que tenía cuando ocurrió**.

### 3. Estados en vez de borrar

Un turno nunca se borra: pasa de `reservado` a `completado`, `ausente` o `cancelado`. La diferencia entre `ausente` (no vino y no avisó) y `cancelado` (avisó) es lo que permite medir faltazos, que es plata perdida.

### 4. Historial con trigger

Cada cambio de estado deja una fila en `turno_evento` con **quién** lo hizo (`cliente`, `barbero` o `sistema`) y **cuándo**. Lo escribe un trigger de PostgreSQL, así que aunque alguien cambie un estado desde otro lado (pgAdmin, un script), el registro queda igual.

La app le dice al trigger quién es el actor con:

```sql
SELECT set_config('app.actor', 'cliente', true);  -- true = solo para esta transacción
```

### 5. El cliente se identifica por teléfono

No pedirle al cliente que se cree una cuenta es clave para que reserve. Pero igual necesitamos reconocerlo cuando vuelve, porque la retención es la métrica más valiosa del proyecto. El teléfono cumple las dos cosas. Se **normaliza** antes de guardarlo (`app/schemas.py`): "+54 9 11 2233-4455" y "11 2233 4455" son la misma persona.

> **Limitación conocida:** el formato viejo con "15" (`11 15 2233 4455`) no se normaliza. Se puede agregar cuando aparezca en datos reales.

## Cómo probarlo

```bash
python -m app.cli inicializar-db
```

Después, desde `psql` o pgAdmin, se puede intentar insertar dos turnos pisados y ver cómo PostgreSQL rechaza el segundo.
