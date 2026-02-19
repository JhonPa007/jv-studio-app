
-- Script de Creación de Tablas para el Módulo JV School (Actualizado)
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
    dias_clase VARCHAR(100),
    hora_inicio VARCHAR(20),
    hora_fin VARCHAR(20),
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
    curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL, 
    grupo_id INTEGER REFERENCES escuela_grupos(id) ON DELETE SET NULL,
    fecha_inscripcion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_inicio_clases DATE,
    costo_matricula_acordado DECIMAL(10, 2), 
    costo_mensualidad_acordada DECIMAL(10, 2), 
    estado VARCHAR(20) DEFAULT 'Activo'
);

-- 4. Tabla Pagos (Historial)
CREATE TABLE IF NOT EXISTS escuela_pagos (
    id SERIAL PRIMARY KEY,
    alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
    monto DECIMAL(10, 2) NOT NULL,
    fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metodo_pago VARCHAR(50), 
    codigo_recibo VARCHAR(50) UNIQUE, -- Nuevo: Para imprimir en el comprobante (ej: REC-001)
    usuario_id INTEGER, 
    observaciones TEXT
);

-- 5. Tabla Cuotas (Cronograma y Estado de Deudas)
CREATE TABLE IF NOT EXISTS escuela_cuotas (
    id SERIAL PRIMARY KEY,
    alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
    concepto VARCHAR(100) NOT NULL, 
    monto_original DECIMAL(10, 2) NOT NULL,
    monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
    saldo DECIMAL(10, 2) DEFAULT 0.00, 
    fecha_vencimiento DATE,
    estado VARCHAR(20) DEFAULT 'Pendiente', 
    orden_pago INTEGER DEFAULT 0 
);

-- 6. Tabla Detalle de Pagos (Para Desglose en Comprobantes)
CREATE TABLE IF NOT EXISTS escuela_pagos_detalle (
    id SERIAL PRIMARY KEY,
    pago_id INTEGER REFERENCES escuela_pagos(id) ON DELETE CASCADE,
    cuota_id INTEGER REFERENCES escuela_cuotas(id) ON DELETE CASCADE,
    monto_aplicado DECIMAL(10, 2) NOT NULL, -- Cuánto de este pago se usó para esta cuota
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices Recomendados
CREATE INDEX IF NOT EXISTS idx_alumnos_dni ON escuela_alumnos(dni);
CREATE INDEX IF NOT EXISTS idx_cuotas_alumno ON escuela_cuotas(alumno_id);
CREATE INDEX IF NOT EXISTS idx_pagos_alumno ON escuela_pagos(alumno_id);
CREATE INDEX IF NOT EXISTS idx_pagos_detalle_pago ON escuela_pagos_detalle(pago_id);
