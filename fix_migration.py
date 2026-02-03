
import os
import psycopg2

def get_db_connection():
    # Try getting DATABASE_URL from env (for cloud)
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return psycopg2.connect(database_url)
    
    # Fallback to local defaults mirroring .env
    # DB_USER="jv_user", DB_PASSWORD="jv123"
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'jv_user'),
        password=os.environ.get('DB_PASSWORD', 'jv123'),
        database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
        port=os.environ.get('DB_PORT', '5432')
    )

def run_migration():
    conn = None
    try:
        print("Connecting to DB...")
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Inspect Columns
        print("--- Columns in 'clientes' ---")
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'clientes';")
        for col in cur.fetchall():
            print(f"- {col[0]} ({col[1]})")
        print("-------------------------------")

        # 2. Add 'saldo_monedero'
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
        if not cur.fetchone():
             print("Adding 'saldo_monedero' column...")
             cur.execute("ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
             conn.commit()
             print("✅ Migration successful: 'saldo_monedero' added.")
        else:
             print("ℹ️ 'saldo_monedero' already exists.")

    except Exception as e:
        print(f"❌ Error: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_migration()
