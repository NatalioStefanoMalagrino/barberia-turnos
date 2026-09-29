# 2. Backend (FastAPI)

## Estructura

```
app/
├── main.py            punto de entrada: arma la app y registra las rutas
├── config.py          lee .env y config/negocio.json
├── db.py              conexión a PostgreSQL + helper de transacción
├── disponibilidad.py  cálculo de horarios libres (función pura)
├── turnos.py          lógica compartida: crear turno, cambiar estado
├── schemas.py         validación de datos de entrada (Pydantic)
├── seguridad.py       hash de contraseñas
├── cli.py             comandos: inicializar-db, crear-usuario
└── routers/
    ├── api.py         /api/...   lo usa el JavaScript de la landing
    ├── web.py         /, /turno/{token}   páginas públicas
    └── panel.py       /panel/... agenda del barbero (con login)
```

**Por qué separar `turnos.py` de los routers:** la web y el panel crean turnos. Si la lógica estuviera en cada endpoint, habría dos versiones que tarde o temprano se desincronizan.

## Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/servicios` | Lista de servicios |
| GET | `/api/barberos` | Lista de barberos |
| GET | `/api/disponibilidad?servicio_id=&fecha=&barbero_id=` | Horarios libres de un día |
| POST | `/api/turnos` | Reservar |
| GET | `/turno/{token}` | Ver el turno |
| POST | `/turno/{token}/cancelar` | Cancelar sin login |

Con el servidor corriendo, en `http://localhost:8000/docs` se pueden probar todos desde el navegador. FastAPI arma esa página sola.

## Cómo se calcula la disponibilidad

```
libres = franjas del día − turnos no cancelados − bloqueos − lo que ya pasó (o es en menos de 1 h)
```

Dentro de lo libre se ofrecen inicios cada 15 minutos **donde entre el servicio completo**. Por eso el cálculo depende del servicio: en un hueco de 45' entra un corte de 30' pero no un combo de 50'.

`disponibilidad.py` es una **función pura**: recibe todo como parámetros (incluido el "ahora") y no toca la base. Eso permite testearla con casos armados a mano (`tests/test_disponibilidad.py`), que es donde se esconden los bugs de un sistema de turnos.

## Qué pasa cuando alguien reserva

1. Pydantic valida los datos (nombre, teléfono, email). Si algo está mal, devuelve **422** con el detalle.
2. Se recalcula la disponibilidad **en el servidor**. Nunca se confía en lo que manda el navegador: alguien podría mandar un horario inventado.
3. Si eligió "cualquiera", se asigna el barbero con **menos minutos reservados ese día**, para repartir el trabajo.
4. Se crea o reconoce al cliente por teléfono (`INSERT ... ON CONFLICT`, en una sola sentencia atómica).
5. Se inserta el turno dentro de un `SAVEPOINT`. Si la constraint de la base lo rechaza (otra persona reservó ese horario un instante antes), se devuelve **409** con un mensaje claro y el formulario recarga los horarios.

## SQL a mano en vez de ORM

Se usa SQLAlchemy "Core" con `text("SELECT ...")`, sin ORM. El proyecto gira alrededor de la base y conviene ver cada consulta. Siempre con parámetros (`:nombre`), **nunca** armando el SQL con f-strings con datos del usuario: eso sería una puerta abierta a SQL injection. Los únicos f-strings que hay en el SQL son para agregar filtros fijos escritos por nosotros.

## Seguridad básica del panel

- Contraseñas con **PBKDF2** (librería estándar de Python), nunca en texto plano.
- Sesión en cookie **firmada** con `SECRET_KEY`: el navegador no la puede modificar.
- `SameSite=lax`: otro sitio no puede mandar formularios al panel usando la sesión del barbero.
- Un barbero solo ve y modifica **sus** turnos; el dueño ve todos.
- Mismo mensaje de error si el usuario no existe o si la contraseña está mal, para no revelar qué usuarios existen.

## Tests

```bash
pytest
```

- `test_disponibilidad.py`: el cálculo de horarios, sin base.
- `test_api.py`: reservas, doble reserva, cancelación, login y panel contra un PostgreSQL real (crea y borra la base `barberia_test`).
- `test_etl.py`: las reglas de segmentación y de capacidad del ETL.

GitHub los corre solos en cada push (`.github/workflows/tests.yml`).
