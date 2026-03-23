import os
import psycopg2

def check_col():
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cursor = conn.cursor()
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'servicios' AND column_name = 'orden'")
        res = cursor.fetchone()
        if res:
            print("Columna 'orden' existe.")
        else:
            print("Columna 'orden' NO existe.")
            
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'productos' AND column_name = 'orden'")
        res = cursor.fetchone()
        if res:
            print("Columna 'orden' (productos) existe.")
        else:
            print("Columna 'orden' (productos) NO existe.")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_col()
