import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def final_fix():
    try:
        print("Connecting to DB...")
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cursor = conn.cursor()
        
        # Read SQL
        with open('crear_tablas_escuela.sql', 'r', encoding='utf-8') as f:
            sql_script = f.read()
            
        print("Executing SQL script...")
        cursor.execute(sql_script)
        conn.commit()
        print("Committed.")
        
        # Verify
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'escuela_%'")
        tables = cursor.fetchall()
        
        with open('schema_result.txt', 'w') as f:
            f.write("Tables found:\n")
            for t in tables:
                f.write(f"- {t[0]}\n")
            if len(tables) >= 5: # We expect at least 5 tables
                f.write("SUCCESS: School tables created.\n")
            else:
                f.write("FAILURE: School tables missing.\n")
                
        cursor.close()
        conn.close()
        
    except Exception as e:
        with open('schema_result.txt', 'w') as f:
            f.write(f"ERROR: {e}\n")
        print(f"Error: {e}")

if __name__ == "__main__":
    final_fix()
