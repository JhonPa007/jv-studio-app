import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

def check_columns():
    # Attempt to load .env if it exists
    if os.path.exists('.env'):
        load_dotenv('.env')
        
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        print("Checking 'servicios' columns:")
        cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'servicios'")
        cols = cursor.fetchall()
        for col in cols:
            print(f" - {col['column_name']} ({col['data_type']})")
            
        print("\nChecking 'productos' columns:")
        cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'productos'")
        cols = cursor.fetchall()
        for col in cols:
            print(f" - {col['column_name']} ({col['data_type']})")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_columns()
