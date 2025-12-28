import psycopg2
import os

# Database configuration from local environment assumptions or hardcoded for this task
# Since I cannot see .env, I rely on 'routes.py' logic usually, but here I'll try to use a direct connection string if available, 
# or reuse the app's get_db logic. 
# Best approach: Create a script that imports `app` and context.

from app import create_app, get_db

app = create_app()

with app.app_context():
    try:
        db = get_db()
        cursor = db.cursor()
        
        print("Creating table 'horarios_extra'...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS horarios_extra (
                id SERIAL PRIMARY KEY,
                empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
                sucursal_id INTEGER REFERENCES sucursales(id) ON DELETE CASCADE,
                fecha DATE NOT NULL,
                hora_inicio TIME NOT NULL,
                hora_fin TIME NOT NULL,
                motivo TEXT,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Verify ausencias_empleado columns just in case
        print("Verifying 'ausencias_empleado' columns...")
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'ausencias_empleado';
        """)
        columns = cursor.fetchall()
        for col in columns:
            print(f" - {col[0]} ({col[1]})")

        db.commit()
        print("Success! Table 'horarios_extra' ready.")
        
    except Exception as e:
        print(f"Error: {e}")
