import psycopg2
from psycopg2.extras import RealDictCursor
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    cursor = db.cursor()
    
    # 1. Crear empleado_deudas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS empleado_deudas (
            id SERIAL PRIMARY KEY,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE CASCADE,
            concepto VARCHAR(255) NOT NULL,
            monto_total DECIMAL(10, 2) NOT NULL,
            monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
            estado VARCHAR(50) DEFAULT 'Pendiente',
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    print("Tabla empleado_deudas creada o verificada.")
    
    # 2. Crear empleado_penalidades
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS empleado_penalidades (
            id SERIAL PRIMARY KEY,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE CASCADE,
            motivo VARCHAR(255) NOT NULL,
            monto DECIMAL(10, 2) NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deducido_en_planilla_id INTEGER REFERENCES planillas(id) ON DELETE SET NULL
        );
    """)
    print("Tabla empleado_penalidades creada o verificada.")
    
    db.commit()
    cursor.close()
    print("Migración de tablas de RRHH completadas con éxito.")
