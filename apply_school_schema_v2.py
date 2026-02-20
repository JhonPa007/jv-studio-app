import psycopg2
from app.db import get_db
from app import create_app
import os

app = create_app()

def apply_schema_v2():
    with app.app_context():
        try:
            db = get_db()
            print(f"Connected to DB: {db}")
            with db.cursor() as cursor:
                # Read the SQL file
                with open('crear_tablas_escuela.sql', 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                
                # Split by semicolon to execute one by one (rudimentary split)
                statements = sql_script.split(';')
                
                for i, stmt in enumerate(statements):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                        
                    print(f"Executing statement {i+1}...")
                    # print(f"SQL: {stmt[:50]}...") # Print first 50 chars
                    try:
                        cursor.execute(stmt)
                        print(f"Statement {i+1} executed successfully.")
                    except Exception as e:
                        print(f"Error executing statement {i+1}: {e}")
                        # Don't break, maybe some tables exist? But we want to see the error.
                        
                db.commit()
                print("All statements executed and committed.")

                # Verify again
                cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'escuela_cursos'")
                if cursor.fetchone()[0] > 0:
                    print("SUCCESS: Tabla 'escuela_cursos' encontrada.")
                else:
                    print("FAILURE: Tabla 'escuela_cursos' NO encontrada.")
                
        except Exception as e:
            print(f"Error checking DB: {e}")

if __name__ == "__main__":
    apply_schema_v2()
