
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
os.environ['PGCLIENTENCODING'] = 'UTF8'

def check_schema():
    conn = None
    try:
        print(f"Connecting to {os.environ.get('DB_NAME')} as {os.environ.get('DB_USER')}...")
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        
        # List all tables
        print("\n--- Tables in public schema ---")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cur.fetchall()
        for t in tables:
            print(f"- {t[0]}")
            
        # Check specific table
        print("\n--- Checking 'packages' ---")
        cur.execute("SELECT to_regclass('public.packages');")
        table_exists = cur.fetchone()[0]
        
        if table_exists:
            print("Table 'packages' exists.")
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'packages';
            """)
            columns = cur.fetchall()
            for col in columns:
                print(f"  * {col[0]} ({col[1]})")
        else:
            print("Table 'packages' DOES NOT exist.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    check_schema()
