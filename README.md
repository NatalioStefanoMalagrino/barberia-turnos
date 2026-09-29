# Sistema de turnos para barberías + capa de datos

Proyecto demo del emprendimiento: una **landing page con reserva de turnos propia**, un **panel para el barbero** y una **capa de ingeniería de datos** (ETL + modelo estrella) para analizar el negocio en **Power BI**.

Está pensado como **plantilla replicable**: para otra barbería se cambian `config/negocio.json` y `db/02_seed.sql`, sin tocar código.

## Stack

| Capa | Tecnología |
|---|---|
| Web y API | Python · FastAPI · Jinja2 · HTML/CSS/JS sin frameworks |
| Base de datos | PostgreSQL |
| Datos | Python · pandas · modelo estrella en el esquema `analytics` |
| Tablero | Power BI Desktop |
| Automatización | GitHub Actions (tests en cada push, ETL todas las noches) |

## Cómo está organizado

```
barberia-turnos/
├── db/
│   ├── 01_schema.sql          modelo transaccional (tablas, constraints, trigger)
│   └── 02_seed.sql            barberos, servicios y horarios de EJEMPLO
├── app/                       backend FastAPI + landing + panel
├── data/
│   ├── generar_datos.py       6 meses de datos simulados realistas
│   ├── analytics_schema.sql   modelo estrella
│   └── etl.py                 extraer → transformar → validar → cargar
├── config/negocio.json        datos y colores de la barbería
├── render.yaml                deploy de la web en Render (Blueprint)
├── tests/                     18 tests (pytest)
├── docs/                      explicación de cada etapa  ← empezá por acá
└── .github/workflows/         tests automáticos y ETL nocturno
```

## Documentación, en orden

1. [Base de datos](docs/01-base-de-datos.md): por qué cada tabla y cada restricción.
2. [Backend](docs/02-backend.md): endpoints, cálculo de disponibilidad, seguridad.
3. [Landing y panel](docs/03-landing-y-panel.md): por qué el panel define la calidad de los datos.
4. [Ingeniería de datos](docs/04-datos.md): datos simulados, modelo estrella, ETL y segmentación.
5. [Power BI](docs/05-power-bi.md): conexión, relaciones, medidas DAX y páginas.
6. [Deploy](docs/06-deploy.md): base en Neon + web en Render, sin correr comandos.

## Subirlo a la nube (lo más fácil)

1. Crear una base en [Neon](https://neon.com) (región AWS US East, sin connection pooling) y copiar la cadena de conexión.
2. En [Render](https://render.com): **New → Blueprint** → elegir este repositorio → pegar la cadena de Neon y una contraseña para el panel → **Apply**.

La app crea sola las tablas, el usuario y los datos de demo. Detalle en [docs/06-deploy.md](docs/06-deploy.md).

## Correrlo en tu máquina

Necesitás Python 3.11+ y PostgreSQL 14+.

```bash
# 1. Entorno
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Base de datos
createdb barberia                    # o crearla desde pgAdmin
cp .env.example .env                 # y completar DATABASE_URL
python -m app.cli inicializar-db
python -m app.cli crear-usuario dueno --password demo1234
python -m app.cli crear-usuario mati --barbero Mati --password demo1234

# 3. Datos simulados + ETL (para la demo)
python -m data.generar_datos --si-borrar-todo
python -m data.etl

# 4. Levantar la web
uvicorn app.main:app --reload
```

- Landing: http://localhost:8000
- Panel: http://localhost:8000/panel (usuario `dueno` o `mati`, contraseña `demo1234`)
- API interactiva: http://localhost:8000/docs

Tests: `pytest` (usa una base aparte, `barberia_test`, que crea y borra sola).

## Estado del roadmap

- [x] Modelo de datos con regla anti-superposición en la base
- [x] Reserva online: servicio → barbero → día → horario → datos
- [x] Cancelación por link, sin login
- [x] Panel: agenda, vino/faltó, turnos manuales, bloqueos
- [x] Datos simulados de 6 meses
- [x] ETL + modelo estrella + segmentación de clientes
- [x] Tests y ETL nocturno en GitHub Actions
- [ ] Datos reales de la barbería (servicios, precios, horarios, fotos)
- [ ] Tablero armado en Power BI (guía en `docs/05-power-bi.md`)
- [x] Deploy sin comandos (Neon + Render Blueprint)
- [ ] Confirmación por email
