
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def check_data():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, descripcion, estado_confirmacion, caja_sesion_id FROM gastos ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
            with open("data_check.txt", "w") as f:
                for row in rows:
                    f.write(f"{row}\n")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_data()
