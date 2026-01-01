
import psycopg2
import sys
import os
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')

def verify_tables():
    print("Verifying tables...")
    conn = None
    try:
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            conn = psycopg2.connect(database_url)
        else:
            conn = psycopg2.connect(
                host=os.environ.get('DB_HOST') or 'localhost',
                user=os.environ.get('DB_USER') or 'postgres',       
                password=os.environ.get('DB_PASSWORD') or 'jv123',
                database=os.environ.get('DB_NAME') or 'jv_studio_pg_db'
            )
            
        cur = conn.cursor()
        
        tables = ['loyalty_rules', 'crm_config']
        for t in tables:
            try:
                cur.execute(f"SELECT count(*) FROM {t}")
                print(f"Table '{t}': EXISTS (Rows: {cur.fetchone()[0]})")
            except Exception as e:
                print(f"Table '{t}': MISSING or Error ({e.__class__.__name__})")
                conn.rollback() # Reset for next check
                
    except Exception as e:
        print(f"Connection Failed: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    verify_tables()
