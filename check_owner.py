
import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()
os.environ['PGCLIENTENCODING'] = 'UTF8'

def check_owner():
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        
        cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'clientes'")
        owner = cur.fetchone()
        
        if owner:
            print(f"Table 'clientes' owner: {owner[0]}")
            print(f"Current user: {os.environ.get('DB_USER')}")
        else:
            print("Table 'clientes' NOT FOUND in pg_tables.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    check_owner()
