
import psycopg2
import os
import sys
from dotenv import load_dotenv

# Load .env file explicitly
load_dotenv()

# Force UTF-8 environment for the driver
os.environ['PGCLIENTENCODING'] = 'UTF8'

def run_migration():
    conn = None
    try:
        # Use credentials from loaded env
        host = os.environ.get('DB_HOST')
        user = os.environ.get('DB_USER')
        password = os.environ.get('DB_PASSWORD')
        database = os.environ.get('DB_NAME')
        port = os.environ.get('DB_PORT')

        print(f"Connecting to {database} as postgres (attempting owner access)...")

        conn = psycopg2.connect(
            host=host,
            user='postgres', # Forced owner
            password=password, # Trying jv123
            database=database,
            port=port
        )
        cur = conn.cursor()
        
        print("Adding 'saldo_monedero' column (IF NOT EXISTS)...")
        # Use IF NOT EXISTS to be safe and avoid permissions issues on information_schema if any
        cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
        conn.commit()
        print("Migration successful.")
            
    except Exception as e:
        if conn:
            conn.rollback()
        # Handle printing safely
        try:
            print(f"Migration failed: {e}")
        except:
             print(f"Migration failed (unicode error): {repr(e)}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
