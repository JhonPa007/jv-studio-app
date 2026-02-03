
import psycopg2
from app.db import get_db_connection

def run_migration():
    conn = None
    try:
        conn = get_db_connection()
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
        print(f"Migration failed: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
