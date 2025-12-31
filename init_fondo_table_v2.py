from app import create_app, db
from app.db import get_db

app = create_app()

with app.app_context():
    conn = get_db()
    with conn.cursor() as cursor:
        try:
            print("Creating 'configuracion_fondo_mensual' table...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS configuracion_fondo_mensual (
                    anio INT NOT NULL,
                    mes INT NOT NULL,
                    empleado_id INT DEFAULT NULL,
                    porcentaje DECIMAL(5,2) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Indexes
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_global 
                ON configuracion_fondo_mensual (anio, mes) 
                WHERE empleado_id IS NULL;
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_empleado 
                ON configuracion_fondo_mensual (anio, mes, empleado_id) 
                WHERE empleado_id IS NOT NULL;
            """)
            
            conn.commit()
            print("Table created successfully!")
            
        except Exception as e:
            print(f"Error: {e}")
            conn.rollback()
