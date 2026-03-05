import psycopg2
import os

try:
    conn = psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'jv123'),
        database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
        port=5432
    )
    with conn.cursor() as cursor:
        cursor.execute("SELECT current_user;")
        print("Connected as:", cursor.fetchone()[0])
        
        cursor.execute("SELECT has_schema_privilege(current_user, 'public', 'CREATE');")
        can_create = cursor.fetchone()[0]
        print("Can create in public:", can_create)
        
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
        conn.commit()
        print("Success!")
except Exception as e:
    import traceback
    with open("err2.txt", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
