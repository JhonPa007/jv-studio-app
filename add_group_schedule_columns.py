import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_connection():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        print(f"Connecting via DATABASE_URL...") 
        return psycopg2.connect(database_url)
    else:
        print("Connecting via Local Defaults (trying .env)...")
        # Check if we have env vars set now
        host = os.environ.get('DB_HOST')
        user = os.environ.get('DB_USER')
        
        if not host and not user:
             print("Warning: DB_HOST and DB_USER not found in environment. Using hardcoded defaults...")
        
        return psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )

def add_columns():
    try:
        conn = get_connection()
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Connected! Adding columns...")
        
        queries = [
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS dias_clase VARCHAR(100);",
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS hora_inicio VARCHAR(20);",
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS hora_fin VARCHAR(20);"
        ]

        for q in queries:
            try:
                cursor.execute(q)
                print(f"Executed: {q}")
            except Exception as e:
                print(f"Error executing query: {repr(e)}")

        print("Migration completed.")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Connection Error: {repr(e)}")

if __name__ == "__main__":
    add_columns()
