"""
Script to create the 'configuracion_fondo_mensual' table.
"""
import psycopg2
import os

# Hardcoded for reliability in this environment
DATABASE_URL = "postgresql://postgres:jv123@localhost:5432/jv_studio_pg_db"

def create_table():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Create table
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
        
        # Unique Index Global
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_global 
            ON configuracion_fondo_mensual (anio, mes) 
            WHERE empleado_id IS NULL;
        """)

        # Unique Index Empleado
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_empleado 
            ON configuracion_fondo_mensual (anio, mes, empleado_id) 
            WHERE empleado_id IS NOT NULL;
        """)

        conn.commit()
        print("Table 'configuracion_fondo_mensual' created successfully.")
        
    except Exception as e:
        print(f"Error creating table: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    create_table()
