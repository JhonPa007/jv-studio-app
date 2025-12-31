"""
Script to create the 'configuracion_fondo_mensual' table.
"""
import psycopg2
import os

DATABASE_URL = os.environ.get('DATABASE_URL')

def create_table():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    try:
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
        
        # Add Unique Constraint/Index to prevent duplicates
        # We need a unique constraint on (anio, mes, empleado_id) 
        # But for unique index, NULLs are usually distinct in standard SQL, though Postgres 15+ allows NULLS NOT DISTINCT.
        # To be safe and compatible, we'll use a partial index approach or just a unique index if the PG version supports it well enough for our logic.
        # Actually, simpler: UNIQUE INDEX on (anio, mes, empleado_id) handles NULLs as distinct entries usually, so multiple global rows (NULL id) might be allowed.
        # To strictly enforce one global setting per month:
        # 1. Index for Global: UNIQUE (anio, mes) WHERE empleado_id IS NULL
        # 2. Index for Employee: UNIQUE (anio, mes, empleado_id) WHERE empleado_id IS NOT NULL

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
        print("Table 'configuracion_fondo_mensual' created successfully.")
    except Exception as e:
        print(f"Error creating table: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    create_table()
