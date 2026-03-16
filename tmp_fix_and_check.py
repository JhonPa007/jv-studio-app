
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def fix_schema_and_check():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor() as cur:
            # Add the missing column if it's missing (to match what's expected)
            try:
                cur.execute("ALTER TABLE gastos ADD COLUMN estado_confirmacion VARCHAR(20) DEFAULT 'Confirmado'")
                print("Added estado_confirmacion column.")
            except:
                conn.rollback()
                print("Column already exists or other error.")
            
            # Now update the NULLs in caja_sesion_id or estado_confirmacion if any
            # (This is just for my local testing, but gives me a clue)
            
            # Let's see the current data
            cur.execute("SELECT id, estado_confirmacion, caja_sesion_id FROM gastos ORDER BY id DESC LIMIT 10")
            for row in cur.fetchall():
                print(row)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_schema_and_check()
