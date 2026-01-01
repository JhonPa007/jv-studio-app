
import psycopg2
import sys

def run_migration():
    conn = None
    try:
        # Connect using the credentials found in app/db.py
        print("Connecting to database...")
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",       
            password="jv123",
            database="jv_studio_pg_db"
        )
        cur = conn.cursor()
        
        # 1. Create loyalty_rules table
        print("Checking/Creating loyalty_rules table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loyalty_rules (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                servicio_id INTEGER REFERENCES servicios(id),
                cantidad_requerida INTEGER NOT NULL,
                periodo_meses INTEGER NOT NULL,
                descuento_porcentaje NUMERIC(5, 2) NOT NULL,
                activo BOOLEAN DEFAULT TRUE
            );
        """)
        
        # 2. Create crm_config table
        print("Checking/Creating crm_config table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS crm_config (
                id SERIAL PRIMARY KEY,
                tipo_evento VARCHAR(50) NOT NULL,
                mensaje_plantilla TEXT,
                dias_anticipacion INTEGER DEFAULT 0,
                activo BOOLEAN DEFAULT TRUE
            );
        """)
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        if conn:
            conn.rollback()
        # Use repr to avoid encoding errors in Windows terminal
        print(f"Error during migration: {repr(e)}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
