import psycopg2
import sys

def fix_and_verify():
    log = []
    conn = None
    try:
        # HARDCODED FROM .env
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",
            password="jv123",
            database="jv_studio_pg_db",
            port="5432"
        )
        # Windows encoding
        try:
             conn.set_client_encoding('LATIN1')
        except:
             pass
        
        conn.autocommit = False
        cursor = conn.cursor()
        
        # 1. Check Connection Info
        cursor.execute("SELECT current_database(), current_user;")
        db_info = cursor.fetchone()
        log.append(f"Connected to: DB={db_info[0]}, User={db_info[1]}")
        
        # 2. Create Table
        log.append("Creating table...")
        create_sql = """
        CREATE TABLE IF NOT EXISTS gift_cards (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) NOT NULL UNIQUE,
            initial_amount DECIMAL(10, 2) NOT NULL CHECK (initial_amount >= 0),
            current_balance DECIMAL(10, 2) NOT NULL CHECK (current_balance >= 0),
            status VARCHAR(20) NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'canjeada', 'vencida', 'anulada')),
            expiration_date DATE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            purchaser_name VARCHAR(255),
            recipient_name VARCHAR(255)
        );
        """
        cursor.execute(create_sql)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gift_cards_code ON gift_cards(code);")
        
        conn.commit()
        log.append("Table created/updated and COMMITTED.")
        
        # 3. Verify
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='gift_cards'")
        cols = cursor.fetchall()
        
        if cols:
            log.append(f"SUCCESS: Found {len(cols)} columns.")
            for c in cols:
                log.append(f" - {c[0]}")
        else:
            log.append("FAILURE: Table still not found after commit!")

    except Exception as e:
        if conn:
            conn.rollback()
        log.append(f"ERROR: {e}")
    finally:
        if conn:
            conn.close()
        
    with open('fix_result.txt', 'w') as f:
        f.write('\n'.join(log))

if __name__ == "__main__":
    fix_and_verify()
