import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def migrate_as_superuser():
    print("Connecting as SUPERUSER (postgres)...")
    try:
        # We try to use 'postgres' user, which typically has superuser rights if it is a local DB
        # If 'jv123' doesn't work for postgres, we might have an issue.
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user='postgres',
            password='jv123', # Common password in this project it seems
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        conn.autocommit = True
        cur = conn.cursor()
        
        # Adding missing columns
        print("1. Fixing 'clientes'...")
        try:
            cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS saldo_monedero DECIMAL(10,2) DEFAULT 0.00")
            print("  - Added saldo_monedero")
        except Exception as e: print(f"  - Error: {e}")

        print("2. Fixing 'venta_items'...")
        try:
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS porcentaje_servicio_extra DECIMAL(5,2) DEFAULT 0.00")
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS comision_servicio_extra DECIMAL(10,2) DEFAULT 0.00")
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS entregado_al_colaborador BOOLEAN DEFAULT FALSE")
            print("  - Added extra columns to venta_items")
        except Exception as e: print(f"  - Error: {e}")

        print("3. Fixing 'comisiones'...")
        try:
            cur.execute("ALTER TABLE comisiones ADD COLUMN IF NOT EXISTS porcentaje DECIMAL(5,2) DEFAULT 0.00")
            print("  - Added porcentaje to comisiones")
        except Exception as e: print(f"  - Error: {e}")

        print("4. Granting permissions to 'jv_user'...")
        try:
            cur.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO jv_user")
            cur.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO jv_user")
            print("  - Permissions granted to jv_user")
        except Exception as e: print(f"  - Error: {e}")

        conn.close()
        print("\nAll done.")
        
    except Exception as e:
        print(f"FAILED to connect as postgres: {e}")
        print("Trying with jv_user just in case...")
        # Fallback to the current user if postgres doesn't work
        # (Though we know jv_user didn't have rights before)

if __name__ == "__main__":
    migrate_as_superuser()
