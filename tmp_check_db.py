import psycopg2
import os

def check_columns(table_name):
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'")
        columns = [row[0] for row in cur.fetchall()]
        print(f"Columns for {table_name}: {', '.join(columns)}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error checking {table_name}: {e}")

check_columns('servicios')
check_columns('productos')
