
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def check_gastos():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, sucursal_id, caja_sesion_id, fecha, monto, estado_confirmacion, empleado_beneficiario_id FROM gastos WHERE id IN (202, 199, 198, 192, 195, 201) ORDER BY id DESC")
            rows = cur.fetchall()
            for row in rows:
                print(row)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_gastos()
