-- =====================================================================
--  Datos iniciales de la barbería
-- =====================================================================
--  ⚠ Barberos, precios y horarios son de EJEMPLO. En la Fase 0 se
--  reemplazan con lo que se releve en la barbería real.
--  Para otro cliente se copia este archivo y se cambian los valores.
-- =====================================================================

INSERT INTO barbero (nombre) VALUES
    ('Mati'),
    ('Leo'),
    ('Nico');

INSERT INTO servicio (nombre, descripcion, duracion_min, precio, orden) VALUES
    ('Corte',            'Corte clásico a tijera y máquina.',             30, 12000, 1),
    ('Fade',             'Degradé a navaja con terminación prolija.',     40, 14000, 2),
    ('Barba',            'Perfilado y arreglo de barba con toalla caliente.', 20,  8000, 3),
    ('Corte + barba',    'El combo completo.',                            50, 18000, 4),
    ('Diseño / cejas',   'Líneas, diseños o perfilado de cejas.',         15,  4000, 5);

-- Horarios: lunes cerrado, martes a viernes 10-20, sábados 9-18.
-- Leo corta al mediodía (dos franjas), para mostrar que el modelo lo soporta.
-- generate_series(2,5) = martes a viernes (ISO: 1 = lunes).
INSERT INTO horario_barbero (barbero_id, dia_semana, hora_desde, hora_hasta)
SELECT b.id, d, '10:00', '20:00'
FROM barbero b, generate_series(2, 5) AS d
WHERE b.nombre IN ('Mati', 'Nico');

INSERT INTO horario_barbero (barbero_id, dia_semana, hora_desde, hora_hasta)
SELECT b.id, d, f.desde::time, f.hasta::time
FROM barbero b,
     generate_series(2, 5) AS d,
     (VALUES ('10:00', '14:00'), ('15:00', '20:00')) AS f(desde, hasta)
WHERE b.nombre = 'Leo';

INSERT INTO horario_barbero (barbero_id, dia_semana, hora_desde, hora_hasta)
SELECT b.id, 6, '09:00', '18:00'
FROM barbero b;
