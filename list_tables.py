import psycopg2
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')
DATABASE_URL = os.getenv('DATABASE_URL')

def list_tables():
    try:
        print(f"Connecting to {DB_NAME} on {DB_HOST}...")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        cur = conn.cursor()
        
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        
        tables = cur.fetchall()
        print("Tables in public schema:")
        for table in tables:
            print(f"- {table[0]}")
            
            # If escuela_grupos exists, print its columns
            if table[0] == 'escuela_grupos':
                print("  Columns in escuela_grupos:")
                cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table[0]}'")
                columns = cur.fetchall()
                for col in columns:
                    print(f"    - {col[0]} ({col[1]})")

        conn.close()
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    list_tables()
