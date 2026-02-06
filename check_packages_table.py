
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def check_table():
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST'),
            database=os.getenv('DB_NAME'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            port=os.getenv('DB_PORT')
        )
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.packages');")
        result = cur.fetchone()[0]
        if result:
            print("Table 'packages' exists.")
            # Check column count or something simple
            cur.execute("SELECT count(*) FROM packages")
            print(f"Row count: {cur.fetchone()[0]}")
        else:
            print("Table 'packages' DOES NOT EXIST.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_table()
