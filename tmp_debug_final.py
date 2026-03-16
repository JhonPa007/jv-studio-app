
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def debug_gastos():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # First, check if column exists
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos' AND column_name = 'estado_confirmacion'")
            if not cur.fetchone():
                print("Column estado_confirmacion MISSING")
            
            cur.execute("SELECT id, descripcion, monto, caja_sesion_id, estado_confirmacion FROM gastos WHERE id IN (202, 199, 198, 192, 195) ORDER BY id DESC")
            rows = cur.fetchall()
            for row in rows:
                print(row)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_gastos()
