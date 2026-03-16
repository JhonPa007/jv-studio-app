
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_column():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos' AND column_name = 'estado_confirmacion'")
            col = cur.fetchone()
            if col:
                print(f"Column {col[0]} exists.")
            else:
                print("Column estado_confirmacion does NOT exist.")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_column()
