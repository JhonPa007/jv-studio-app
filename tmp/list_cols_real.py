import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def list_columns():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        with conn.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'clientes' ORDER BY ordinal_position")
            rows = cur.fetchall()
            print("Columnas de clientes:")
            for r in rows:
                print(r[0])
        conn.close()
    except Exception as e:
        print(f"Error list_columns: {e}")

if __name__ == "__main__":
    list_columns()
