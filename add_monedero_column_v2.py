
import psycopg2
import os
import sys

# Force UTF-8 for stdout just in case
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def run_migration():
    conn = None
    try:
        print("Connecting to DB...")
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        
        print("Checking column...")
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
        if not cur.fetchone():
            print("Adding 'saldo_monedero' column...")
            cur.execute("ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
            conn.commit()
            print("Migration successful: Column added.")
        else:
            print("Migration successful: Column already exists.")
            
    except Exception as e:
        if conn:
            conn.rollback()
        err_msg = f"Migration failed: {e}"
        print(err_msg)
        with open("migration_error.log", "w", encoding="utf-8") as f:
            f.write(err_msg)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
