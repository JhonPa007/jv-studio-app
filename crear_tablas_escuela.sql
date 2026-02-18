
-- Script de Creación de Tablas para el Módulo JV School
-- Ejecutar en la base de datos PostgreSQL

-- 1. Tabla Cursos
CREATE TABLE IF NOT EXISTS escuela_cursos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    costo_matricula DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    costo_mensualidad DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    duracion_meses INTEGER NOT NULL DEFAULT 1,
    activo BOOLEAN DEFAULT TRUE
);

-- 2. Tabla Grupos
CREATE TABLE IF NOT EXISTS escuela_grupos (
    id SERIAL PRIMARY KEY,
    codigo_grupo VARCHAR(50) NOT NULL UNIQUE,
    curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
    fecha_inicio DATE,
    activo BOOLEAN DEFAULT TRUE
);

-- 3. Tabla Alumnos
CREATE TABLE IF NOT EXISTS escuela_alumnos (
    id SERIAL PRIMARY KEY,
    codigo_alumno VARCHAR(50) UNIQUE, 
    nombres VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100),
    dni VARCHAR(20),
    telefono VARCHAR(20),
    curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL, -- Referencia rápida (opcional pero útil)
    grupo_id INTEGER REFERENCES escuela_grupos(id) ON DELETE SET NULL,
    fecha_inscripcion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_inicio_clases DATE,
    costo_matricula_acordado DECIMAL(10, 2), -- Por si difiere del default del curso
    costo_mensualidad_acordada DECIMAL(10, 2), -- Por si difiere del default del curso
    estado VARCHAR(20) DEFAULT 'Activo' -- Activo, Retirado, Egresado
);

-- 4. Tabla Pagos (Historial)
CREATE TABLE IF NOT EXISTS escuela_pagos (
    id SERIAL PRIMARY KEY,
    alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
    monto DECIMAL(10, 2) NOT NULL,
    fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metodo_pago VARCHAR(50), -- Efectivo, Yape, Plin, Tarjeta
    usuario_id INTEGER, -- ID del empleado que registró el pago
    observaciones TEXT
);

-- 5. Tabla Cuotas (Cronograma y Estado de Deudas)
CREATE TABLE IF NOT EXISTS escuela_cuotas (
    id SERIAL PRIMARY KEY,
    alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
    concepto VARCHAR(100) NOT NULL, -- Ej: 'Matrícula', 'Mensualidad 1', 'Mensualidad 2'
    monto_original DECIMAL(10, 2) NOT NULL,
    monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
    saldo DECIMAL(10, 2) DEFAULT 0.00, -- Se calcula en app o trigger: monto_original - monto_pagado
    fecha_vencimiento DATE,
    estado VARCHAR(20) DEFAULT 'Pendiente', -- Pendiente, Parcial, Completo
    orden_pago INTEGER DEFAULT 0 -- 0=Matrícula, 1=Mes 1, 2=Mes 2... para orden de pago en cascada
);

-- Índices Recomendados
CREATE INDEX IF NOT EXISTS idx_alumnos_dni ON escuela_alumnos(dni);
CREATE INDEX IF NOT EXISTS idx_cuotas_alumno ON escuela_cuotas(alumno_id);
CREATE INDEX IF NOT EXISTS idx_pagos_alumno ON escuela_pagos(alumno_id);
