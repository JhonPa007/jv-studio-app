
import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()
os.environ['PGCLIENTENCODING'] = 'UTF8'

def test_create_table():
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
        
        print("Attempting to CREATE TABLE 'test_permission'...")
        cur.execute("CREATE TABLE IF NOT EXISTS test_permission (id SERIAL PRIMARY KEY, note TEXT);")
        conn.commit()
        print("SUCCESS: Table created.")
        
        print("Attempting to DROP TABLE 'test_permission'...")
        cur.execute("DROP TABLE test_permission;")
        conn.commit()
        print("SUCCESS: Table dropped.")
            
    except Exception as e:
        print(f"FAILED: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    test_create_table()
