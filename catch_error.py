import sys
import traceback
from app import create_app
from app.db import get_db

try:
    app = create_app()
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
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
        print("Success empleado_deudas")
        
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
        print("Success empleado_penalidades")
        
except Exception as e:
    with open("error_log.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("Error caught and written to error_log.txt")
