-- =====================================================================
--  Sistema de turnos para barberías: modelo transaccional (OLTP)
-- =====================================================================
--  Este esquema es el que usa la web para registrar turnos día a día.
--  El modelo estrella para Power BI vive aparte, en el esquema
--  "analytics" (ver data/analytics_schema.sql).
--
--  Convenciones:
--   * Nombres en español y en singular (barbero, servicio, turno).
--   * Toda fecha y hora se guarda como timestamptz (con zona horaria).
--   * Las reglas de negocio críticas las impone la BASE, no solo la app.
-- =====================================================================

-- btree_gist permite combinar "=" (sobre un entero) y "&&" (superposición
-- de rangos de tiempo) en una misma restricción. Lo necesitamos para
-- impedir turnos superpuestos del mismo barbero.
CREATE EXTENSION IF NOT EXISTS btree_gist;
-- pgcrypto aporta gen_random_uuid() en versiones viejas de Postgres.
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- ---------------------------------------------------------------------
--  Catálogos: quién atiende y qué se ofrece
-- ---------------------------------------------------------------------

CREATE TABLE barbero (
    id          SERIAL PRIMARY KEY,
    nombre      TEXT        NOT NULL,
    activo      BOOLEAN     NOT NULL DEFAULT TRUE,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE servicio (
    id           SERIAL PRIMARY KEY,
    nombre       TEXT          NOT NULL UNIQUE,
    descripcion  TEXT,
    duracion_min INTEGER       NOT NULL CHECK (duracion_min > 0 AND duracion_min % 5 = 0),
    precio       NUMERIC(12,2) NOT NULL CHECK (precio >= 0),   -- precio VIGENTE
    activo       BOOLEAN       NOT NULL DEFAULT TRUE,
    orden        INTEGER       NOT NULL DEFAULT 0              -- orden en la landing
);

-- Franjas de trabajo semanales. Un barbero puede tener varias franjas el
-- mismo día (ej. 10-14 y 16-20 si corta al mediodía).
-- dia_semana sigue la norma ISO: 1 = lunes ... 7 = domingo.
CREATE TABLE horario_barbero (
    id          SERIAL PRIMARY KEY,
    barbero_id  INTEGER  NOT NULL REFERENCES barbero(id) ON DELETE CASCADE,
    dia_semana  SMALLINT NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),
    hora_desde  TIME     NOT NULL,
    hora_hasta  TIME     NOT NULL,
    CHECK (hora_desde < hora_hasta),
    UNIQUE (barbero_id, dia_semana, hora_desde)
);

-- Excepciones puntuales al horario: vacaciones, franco, trámite, etc.
CREATE TABLE bloqueo (
    id          SERIAL PRIMARY KEY,
    barbero_id  INTEGER     NOT NULL REFERENCES barbero(id) ON DELETE CASCADE,
    desde       TIMESTAMPTZ NOT NULL,
    hasta       TIMESTAMPTZ NOT NULL,
    motivo      TEXT,
    creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (desde < hasta)
);
CREATE INDEX ix_bloqueo_barbero_periodo
    ON bloqueo USING gist (barbero_id, tstzrange(desde, hasta, '[)'));


-- ---------------------------------------------------------------------
--  Clientes
-- ---------------------------------------------------------------------
-- El cliente se identifica por TELÉFONO: no hay usuario ni contraseña.
-- Así, si vuelve a reservar, lo reconocemos sin pedirle que se registre,
-- y podemos medir retención (cuántas veces viene y cada cuánto).
CREATE TABLE cliente (
    id         SERIAL PRIMARY KEY,
    nombre     TEXT        NOT NULL,
    telefono   TEXT        NOT NULL UNIQUE CHECK (telefono ~ '^[0-9]{8,15}$'),  -- solo dígitos
    email      TEXT,
    creado_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------
--  Turnos (el corazón del sistema)
-- ---------------------------------------------------------------------
CREATE TABLE turno (
    id                 SERIAL PRIMARY KEY,
    cliente_id         INTEGER       NOT NULL REFERENCES cliente(id),
    barbero_id         INTEGER       NOT NULL REFERENCES barbero(id),
    servicio_id        INTEGER       NOT NULL REFERENCES servicio(id),
    inicio             TIMESTAMPTZ   NOT NULL,
    fin                TIMESTAMPTZ   NOT NULL,

    -- Se guarda el precio del MOMENTO de la reserva. Con inflación, el
    -- precio de "servicio" cambia; si calculáramos ingresos históricos
    -- con el precio actual, los números del pasado quedarían inflados.
    precio_cobrado     NUMERIC(12,2) NOT NULL CHECK (precio_cobrado >= 0),

    -- reservado  -> todavía no pasó
    -- completado -> el cliente vino y se lo atendió
    -- ausente    -> no vino y no avisó (el famoso "faltazo")
    -- cancelado  -> avisó que no venía (libera el horario)
    estado             TEXT          NOT NULL DEFAULT 'reservado'
                       CHECK (estado IN ('reservado', 'completado', 'ausente', 'cancelado')),

    -- 'web' = lo reservó el cliente; 'manual' = lo cargó el barbero
    -- (llamada, WhatsApp, cliente que entró sin turno). Sirve para medir
    -- cuánto se usa la reserva online.
    origen             TEXT          NOT NULL DEFAULT 'web'
                       CHECK (origen IN ('web', 'manual')),

    -- Token secreto para que el cliente cancele desde un link, sin login.
    token_cancelacion  UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    creado_en          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    actualizado_en     TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CHECK (inicio < fin),

    -- *** La regla más importante del sistema ***
    -- Un barbero no puede tener dos turnos que se pisen.
    -- tstzrange(inicio, fin, '[)') es el intervalo [inicio, fin): incluye
    -- el inicio y excluye el fin, así un turno 10:00-10:30 y otro
    -- 10:30-11:00 NO se consideran superpuestos.
    -- Los cancelados no cuentan: liberan el lugar.
    -- Si dos personas reservan el mismo horario al mismo milisegundo, la
    -- validación en Python de las dos puede pasar, pero esta restricción
    -- deja entrar a una sola. La otra recibe un error y le avisamos.
    CONSTRAINT turno_sin_superposicion EXCLUDE USING gist (
        barbero_id WITH =,
        tstzrange(inicio, fin, '[)') WITH &&
    ) WHERE (estado <> 'cancelado')
);

CREATE INDEX ix_turno_inicio  ON turno (inicio);
CREATE INDEX ix_turno_cliente ON turno (cliente_id);


-- ---------------------------------------------------------------------
--  Historial de estados (auditoría + materia prima para analítica)
-- ---------------------------------------------------------------------
-- Cada vez que un turno se crea o cambia de estado se agrega una fila
-- acá. Nunca se modifica ni se borra: es un registro de eventos.
-- Con esto podemos responder, por ejemplo, "¿con cuántas horas de
-- anticipación cancelan?", que con solo la tabla turno sería imposible.
CREATE TABLE turno_evento (
    id               BIGSERIAL PRIMARY KEY,
    turno_id         INTEGER     NOT NULL REFERENCES turno(id) ON DELETE CASCADE,
    estado_anterior  TEXT,                      -- NULL cuando se crea el turno
    estado_nuevo     TEXT        NOT NULL,
    actor            TEXT        NOT NULL DEFAULT 'sistema'
                     CHECK (actor IN ('cliente', 'barbero', 'sistema')),
    ocurrido_en      TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_turno_evento_turno ON turno_evento (turno_id);


-- El historial lo escribe un TRIGGER y no la aplicación. Motivo: si
-- mañana alguien cambia un estado desde otro lugar (un script, pgAdmin,
-- otro endpoint), el evento se registra igual. La app no se puede
-- "olvidar" de guardarlo.

-- 1) Antes de actualizar: si quien hace el UPDATE no fijó
--    actualizado_en a mano, lo ponemos en now(). (El generador de datos
--    de prueba sí lo fija, para simular cambios en fechas pasadas.)
CREATE FUNCTION turno_marcar_actualizacion() RETURNS trigger AS $$
BEGIN
    IF NEW.actualizado_en IS NOT DISTINCT FROM OLD.actualizado_en THEN
        NEW.actualizado_en := now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_turno_actualizado
    BEFORE UPDATE ON turno
    FOR EACH ROW EXECUTE FUNCTION turno_marcar_actualizacion();

-- 2) Después de insertar o cambiar el estado: registrar el evento.
--    El "actor" lo informa la app con: SET LOCAL app.actor = 'cliente'
CREATE FUNCTION turno_registrar_evento() RETURNS trigger AS $$
DECLARE
    v_actor TEXT := coalesce(nullif(current_setting('app.actor', true), ''), 'sistema');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO turno_evento (turno_id, estado_anterior, estado_nuevo, actor, ocurrido_en)
        VALUES (NEW.id, NULL, NEW.estado, v_actor, NEW.creado_en);
    ELSIF NEW.estado IS DISTINCT FROM OLD.estado THEN
        INSERT INTO turno_evento (turno_id, estado_anterior, estado_nuevo, actor, ocurrido_en)
        VALUES (NEW.id, OLD.estado, NEW.estado, v_actor, NEW.actualizado_en);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_turno_evento
    AFTER INSERT OR UPDATE OF estado ON turno
    FOR EACH ROW EXECUTE FUNCTION turno_registrar_evento();


-- ---------------------------------------------------------------------
--  Usuarios del panel (barberos y dueño)
-- ---------------------------------------------------------------------
-- barbero_id NULL = dueño/encargado: ve la agenda de todos.
-- La contraseña se guarda HASHEADA (PBKDF2), nunca en texto plano.
CREATE TABLE usuario_panel (
    id             SERIAL PRIMARY KEY,
    usuario        TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,
    barbero_id     INTEGER REFERENCES barbero(id),
    activo         BOOLEAN NOT NULL DEFAULT TRUE
);
