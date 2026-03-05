from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    
    tablas = [
        """
        CREATE TABLE IF NOT EXISTS empleado_deudas (
            id SERIAL PRIMARY KEY,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE CASCADE,
            concepto VARCHAR(255) NOT NULL,
            monto_total DECIMAL(10, 2) NOT NULL,
            monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
            estado VARCHAR(50) DEFAULT 'Pendiente',
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS empleado_penalidades (
            id SERIAL PRIMARY KEY,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE CASCADE,
            motivo VARCHAR(255) NOT NULL,
            monto DECIMAL(10, 2) NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deducido_en_planilla_id INTEGER REFERENCES planillas(id) ON DELETE SET NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS empleado_bonos (
            id SERIAL PRIMARY KEY,
            empleado_id INTEGER REFERENCES empleados(id) ON DELETE CASCADE,
            motivo VARCHAR(255) NOT NULL,
            monto DECIMAL(10, 2) NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deducido_en_planilla_id INTEGER REFERENCES planillas(id) ON DELETE SET NULL
        );
        """
    ]
    
    for idx, table_sql in enumerate(tablas):
        cursor = db.cursor()
        try:
            cursor.execute(table_sql)
            db.commit()
            print(f"Tabla {idx} procesada correctamente.")
        except Exception as e:
            db.rollback()
            print(f"Error en tabla {idx}: {str(e)}")
        finally:
            cursor.close()
    
    print("Migración final terminada.")
