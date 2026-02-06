import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        port=os.getenv('DB_PORT')
    )

try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'servicios'")
    columns = cur.fetchall()
    
    print("SERVICIOS TABLE SCHEMA:")
    if not columns:
        print("Table 'servicios' does not exist.")
    for col in columns:
        print(f"- {col[0]}: {col[1]}")
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
