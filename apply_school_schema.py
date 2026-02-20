import psycopg2
from app.db import get_db
from app import create_app
import os

app = create_app()

def apply_schema():
    with app.app_context():
        try:
            db = get_db()
            with db.cursor() as cursor:
                # Read the SQL file
                with open('crear_tablas_escuela.sql', 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                
                print("Executing SQL script...")
                cursor.execute(sql_script)
                db.commit()
                print("Schema applied successfully!")

                # Verify table existence immediately
                cursor.execute("SELECT to_regclass('public.escuela_cursos');")
                result = cursor.fetchone()
                if result[0]:
                    print("Verification: Table 'escuela_cursos' exists.")
                else:
                    print("Verification: Table 'escuela_cursos' DOES NOT exist.")
                
        except Exception as e:
            print(f"Error applying schema: {e}")

if __name__ == "__main__":
    apply_schema()
