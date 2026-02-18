
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except:
            pass
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

def list_tables():
    conn = get_db_connection()
    if not conn:
        print("No connection")
        return

    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
        AND table_name LIKE 'escuela_%';
    """)
    rows = cur.fetchall()
    print("Tablas encontradas:")
    for row in rows:
        print(row[0])
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    list_tables()
