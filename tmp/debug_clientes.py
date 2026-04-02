import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_client():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        with conn.cursor() as cur:
            cur.execute("SELECT id, razon_social_nombres FROM clientes WHERE razon_social_nombres ILIKE '%Shamir%'")
            rows = cur.fetchall()
            print(f"Encontrados: {len(rows)}")
            for r in rows:
                print(r)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_client()
