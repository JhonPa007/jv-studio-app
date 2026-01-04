
import psycopg2
from app.db import get_db_connection
import os
from dotenv import load_dotenv

load_dotenv()

def migrate():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check columns
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'clientes';")
        columns = [row[0] for row in cur.fetchall()]
        
        print(f"Current columns: {columns}")
        
        if 'apellido_paterno' not in columns:
            print("Adding apellido_paterno...")
            cur.execute("ALTER TABLE clientes ADD COLUMN apellido_paterno VARCHAR(100);")
            
        if 'apellido_materno' not in columns:
            print("Adding apellido_materno...")
            cur.execute("ALTER TABLE clientes ADD COLUMN apellido_materno VARCHAR(100);")
            
        if 'fecha_nacimiento' not in columns:
            print("Adding fecha_nacimiento...")
            cur.execute("ALTER TABLE clientes ADD COLUMN fecha_nacimiento DATE;")
        else:
            print("fecha_nacimiento already exists.")

        conn.commit()
        cur.close()
        conn.close()
        print("Migration complete.")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    migrate()
