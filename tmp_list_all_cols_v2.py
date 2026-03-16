
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_all_columns():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos'")
            cols = [c[0] for c in cur.fetchall()]
            with open("cols_list.txt", "w") as f:
                f.write("Columns in gastos:\n")
                for c in sorted(cols):
                    f.write(f"  {c}\n")
        conn.close()
    except Exception as e:
        with open("cols_list.txt", "w") as f:
            f.write(f"Error: {e}\n")

if __name__ == "__main__":
    check_all_columns()
