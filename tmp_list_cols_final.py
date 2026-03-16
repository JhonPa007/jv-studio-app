
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def list_columns():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos' ORDER BY column_name")
            columns = [c[0] for c in cur.fetchall()]
            print("Columns in gastos:")
            for col in columns:
                print(f"- {col}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_columns()
