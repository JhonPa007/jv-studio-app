
import psycopg2
import sys
import os

def force_migration():
    print("Starting force migration (Environment Aware)...")
    conn = None
    try:
        # Check for DATABASE_URL like the app does
        database_url = os.environ.get('DATABASE_URL')
        
        if database_url:
            print("Using DATABASE_URL from environment.")
            conn = psycopg2.connect(database_url)
        else:
            print("Using localhost fallback.")
            conn = psycopg2.connect(
                host="localhost",
                user="postgres",       
                password="jv123",
                database="jv_studio_pg_db"
            )
        print("Connected.")
        
        cur = conn.cursor()
        
        # 1. Loyalty Rules
        print("Creating table: loyalty_rules")
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
        
        # 2. CRM Config
        print("Creating table: crm_config")
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
        print("Migration SUCCESS.")
        
    except Exception as e:
        # Safe print
        try:
            print(f"MIGRATION FAILED: {str(e)}")
        except:
            print("MIGRATION FAILED (Error message encoding issue)")
            
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    force_migration()
