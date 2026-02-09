
import psycopg2
import os

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'jv123'),
        database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
        port=os.environ.get('DB_PORT', '5432')
    )

def run_migration():
    conn = None
    try:
        conn = get_db_connection()
        # Removed encoding setting to avoid Windows crash

        cur = conn.cursor()
        
        # Check if column exists
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
        if not cur.fetchone():
            print("Adding 'saldo_monedero' column to 'clientes' table...")
            cur.execute("ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
            conn.commit()
            print("Migration successful.")
        else:
            print("Column 'saldo_monedero' already exists.")
            
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Migration failed: {repr(e)}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
