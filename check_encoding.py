import psycopg2
import os

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'jv123'),
        database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
        port=os.environ.get('DB_PORT', '5432')
    )

try:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SHOW server_encoding")
    print(f"Server: {cur.fetchone()[0]}")
    cur.execute("SHOW client_encoding")
    print(f"Client: {cur.fetchone()[0]}")
    conn.close()
except Exception:
    print("Failed")
