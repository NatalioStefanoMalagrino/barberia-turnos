# 3. Landing y panel del barbero

## Landing (`app/templates/index.html`)

HTML con plantillas Jinja2, CSS propio y JavaScript sin frameworks.

**Por qué sin framework:** es una página con un formulario de 4 pasos. Un framework sumaría una etapa de compilación, dependencias y complejidad sin aportar nada. Así, cualquier desarrollador la puede mantener y carga rapidísimo en el celular.

**Pensada primero para el celular:** casi todos los clientes van a entrar desde el link de la bio de Instagram. Detalles que importan ahí:

- Botones de al menos 44 px de alto (tamaño de dedo).
- Inputs con letra de 16 px: con menos, el iPhone hace zoom solo al tocar el campo.
- `inputmode="tel"` en el teléfono: abre el teclado numérico.
- Los días se deslizan horizontalmente, no son un calendario chico.

**Plantilla replicable:** nombre, slogan, dirección, WhatsApp, Instagram, horarios y **colores** salen de `config/negocio.json`. Servicios y barberos salen de la base. Para otra barbería no se toca código: se cambia ese JSON y `db/02_seed.sql`.

### Qué falta para la versión real

- **Fotos:** el hero, la galería y las fotos de los barberos tienen fondos provisorios. Van en `app/static/img/` (el HTML indica dónde).
- **Dirección y mapa reales**, y los valores marcados como EJEMPLO en el JSON.
- **Confirmación por email o WhatsApp:** hoy la confirmación se muestra en pantalla con el link del turno. El email es el siguiente paso natural. WhatsApp automático requiere la API oficial de Meta, que tiene costo y trámite.

## Panel (`/panel`)

Usuarios de ejemplo (se crean con `python -m app.cli crear-usuario ...`):

- `dueno`: ve la agenda de todos.
- `mati`: ve solo la suya.

Qué permite:

- Ver la agenda del día, con flechas para moverse entre días.
- Resumen del día: pendientes, atendidos, faltazos y cuánto se cobró.
- **✓ Vino / ✗ Faltó / Cancelar** en cada turno, con un toque.
- Marca de **"Nuevo"** en los clientes que vienen por primera vez.
- Link directo a WhatsApp del cliente.
- Cargar turnos que llegan por WhatsApp o teléfono, o gente que entra sin turno (quedan con `origen = 'manual'`).
- Bloquear horarios: franco, trámite, vacaciones.

### Por qué el panel es parte de la ingeniería de datos

Parece una pantalla de gestión, pero **define la calidad de los datos de todo el proyecto**:

- Si el barbero no marca quién vino, no hay tasa de faltazos.
- Si no carga los turnos de WhatsApp, la ocupación medida va a ser más baja que la real.
- Si no carga sus vacaciones, esa semana va a parecer un bajón.

Por eso todo se hace en uno o dos toques, y cada botón es un formulario HTML común que funciona aunque falle el JavaScript. La calidad de los datos se decide en la carga, no en el dashboard.
