# 6. Subirlo a internet (Neon + Render)

| Pieza | Dónde | Costo |
|---|---|---|
| Código | GitHub (repositorio privado) | Gratis |
| Base de datos | [Neon](https://neon.com) | Gratis, sin vencimiento |
| Web | [Render](https://render.com), con el Blueprint `render.yaml` | Gratis |

Al arrancar por primera vez, la app crea sola las tablas, el usuario del panel y los datos de demo (ver [`app/arranque.py`](../app/arranque.py)). **No hay que correr ningún comando en tu compu.**

## Paso 1: Subir el código a GitHub

1. En GitHub: **New repository** → `barberia-turnos` → **Private** → crear (sin README).
2. En la carpeta del proyecto:
   ```bash
   git init
   git add .
   git commit -m "Primera versión"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/barberia-turnos.git
   git push -u origin main
   ```
3. En la pestaña **Actions** se corren los tests solos. Tienen que salir en verde.

## Paso 2: Crear la base en Neon

1. Creá una cuenta en [neon.com](https://neon.com) (podés entrar con GitHub).
2. **New project**:
   - **Name:** `barberia`
   - **Postgres version:** la que venga por defecto (16 o más nueva).
   - **Region:** **AWS US East (N. Virginia)**.
3. En el panel del proyecto, botón **Connect**:
   - **Desactivá "Connection pooling"**. El host de la URL tiene que quedar **sin** `-pooler`.
   - Copiá la cadena completa. Es parecida a:
     ```
     postgresql://neondb_owner:abc123@ep-algo-123456.us-east-1.aws.neon.tech/neondb?sslmode=require
     ```
   - Guardala: la vas a pegar en Render y en GitHub.

**Por qué Virginia y no São Paulo:** lo que más importa es que la web y la base estén cerca, porque cada página hace varias consultas. Render no tiene región en Sudamérica, así que la web va en Virginia y la base también. El usuario en Buenos Aires hace un solo viaje hasta allá por página; si la base quedara en São Paulo, cada consulta haría el viaje Virginia–São Paulo.

**Por qué sin pooling:** el pooler de Neon trabaja en un modo que se lleva mal con las consultas preparadas que usa psycopg y produce errores intermitentes. Con el tráfico de una barbería, la conexión directa sobra.

**No hace falta editar la URL:** la app le agrega sola el `+psycopg` que necesita SQLAlchemy.

## Paso 3: Crear la web en Render con el Blueprint

1. Creá una cuenta en [render.com](https://render.com) **con tu cuenta de GitHub**.
2. **New → Blueprint** → elegí el repositorio `barberia-turnos` (si no aparece, **Configure GitHub** y dale acceso).
3. Render lee el `render.yaml` y te pide dos datos:
   - **`DATABASE_URL`**: la cadena de Neon del paso 2, tal cual.
   - **`ADMIN_PASSWORD`**: inventá una contraseña para el panel y anotala.
4. **Apply**. Esperá unos 5 minutos.
5. Entrá al servicio `barberia-turnos`: arriba está tu URL, tipo `https://barberia-turnos-xxxx.onrender.com`.

Listo:

- `https://tu-url.onrender.com`: la landing.
- `https://tu-url.onrender.com/panel`: usuario **`dueno`** y la contraseña del paso 3.
- `https://tu-url.onrender.com/docs`: la API interactiva.

En los **Logs** del servicio vas a ver, en el primer arranque, "Base vacía: creando tablas", "Usuario 'dueno' creado" y "Cargando datos de demo".

## Paso 4: ETL todas las noches (GitHub Actions)

1. En GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
2. Nombre `DATABASE_URL`, valor la cadena de Neon.
3. **Actions → ETL nocturno → Run workflow** para probarlo una vez. Después corre solo a las 3:17 de Argentina.

Además, en el panel el dueño tiene el botón **"Actualizar datos del tablero"**, que corre el ETL en el momento.

## Paso 5: Conectar Power BI a Neon

Seguí [`05-power-bi.md`](05-power-bi.md) con estos datos en vez de `localhost`:

- **Servidor:** el host de la URL (`ep-algo-123456.us-east-1.aws.neon.tech`).
- **Base de datos:** `neondb`.
- **Usuario y contraseña:** los de la URL (`neondb_owner` y lo que sigue a los dos puntos).

## Cada vez que cambies el código

`git push`, y Render redeploya solo en unos minutos.

## Lo que tenés que saber de los planes gratis

- **La web se duerme** a los 15 minutos sin visitas, y la primera visita tarda alrededor de un minuto en despertarla. Antes del pitch, abrila un rato antes.
- **La base también se duerme** a los 5 minutos sin uso, pero se despierta en un momento con la primera consulta.
- Render da 750 horas gratis por mes: alcanza para tener una web prendida todo el mes.

## Si algo falla

| Síntoma | Causa probable |
|---|---|
| `SSL connection is required` | Falta `?sslmode=require` al final de la URL |
| `password authentication failed` | La URL se copió incompleta o con la contraseña mal |
| Errores intermitentes tipo "prepared statement already exists" | Usaste el host con `-pooler`: volvé a copiar la URL con pooling desactivado |
| Las páginas tardan varios segundos siempre (no solo la primera) | La base y la web están en regiones distintas |
| El panel dice usuario o contraseña incorrectos | `ADMIN_PASSWORD` se cargó después del primer arranque: el usuario no se creó. Corré el workflow "Preparar base de demo" o creá el usuario con `python -m app.cli crear-usuario dueno` apuntando a Neon |

## Cuando haya un cliente real

- **Proyecto de Neon aparte** para producción. La demo tiene datos inventados y no se mezclan.
- En el servicio de Render de producción, **borrá la variable `CARGAR_DEMO`**, para que nunca cargue datos simulados.
- Valores de EJEMPLO reemplazados en `config/negocio.json` y `db/02_seed.sql`, y fotos reales en `app/static/img/`.
- Reserva probada desde un celular real con datos móviles.
- Contraseña del panel entregada al dueño por un canal privado.
