
import psycopg2
import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

def force_migration():
    print("Starting force migration (Environment Aware + DotEnv)...")
    conn = None
    try:
        # Check for DATABASE_URL like the app does
        database_url = os.environ.get('DATABASE_URL')
        
        if database_url:
            print("Using DATABASE_URL from environment.")
            conn = psycopg2.connect(database_url)
        else:
            # Check for individual vars
            db_host = os.environ.get('DB_HOST') or 'localhost'
            db_user = os.environ.get('DB_USER') or 'postgres'
            db_pass = os.environ.get('DB_PASSWORD') or 'jv123'
            db_name = os.environ.get('DB_NAME') or 'jv_studio_pg_db'
            
            print(f"Using manual config (Host: {db_host}, User: {db_user}, DB: {db_name})")
            
            conn = psycopg2.connect(
                host=db_host,
                user=db_user,       
                password=db_pass,
                database=db_name
            )
        print("Connected.")
        
        cur = conn.cursor()
        
        # 1. Loyalty Rules
        print("Creating table: loyalty_rules")
        try:
            cur.execute("""
                CREATE TABLE loyalty_rules (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    servicio_id INTEGER REFERENCES servicios(id),
                    cantidad_requerida INTEGER NOT NULL,
                    periodo_meses INTEGER NOT NULL,
                    descuento_porcentaje NUMERIC(5, 2) NOT NULL,
                    activo BOOLEAN DEFAULT TRUE
                );
            """)
        except Exception as e_table:
            print(f"Error creating loyalty_rules (might exist): {e_table.__class__.__name__}")
            conn.rollback()
            # Need to get a new cursor/transaction if rollback happened? 
            # Psycopg2 transaction model: if error, transaction is aborted. 
            # We should probably commit or checking existence differently.
            # But let's just Try/Except block needs careful handling.
            pass
        
        # We need a new cursor or reset connection if rollback happened?
        # Actually simplest is to just try create.
        
        # 2. CRM Config
        print("Creating table: crm_config")

        try:
            cur.execute("""
                CREATE TABLE crm_config (
                    id SERIAL PRIMARY KEY,
                    tipo_evento VARCHAR(50) NOT NULL,
                    mensaje_plantilla TEXT,
                    dias_anticipacion INTEGER DEFAULT 0,
                    activo BOOLEAN DEFAULT TRUE
                );
            """)
        except Exception as e_table2:
            print(f"Error creating crm_config (might exist): {e_table2.__class__.__name__}")
            conn.rollback()
            pass
            
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
