import psycopg2
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')

def get_db_connection():
    if DATABASE_URL:
        try:
            print("Connecting using DATABASE_URL...")
            return psycopg2.connect(DATABASE_URL)
        except Exception as e:
            print(f"Error connecting via DATABASE_URL: {e}")
            return None
    
    try:
        print(f"Connecting using local credentials ({DB_HOST})...")
        return psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return None

def run_migration():
    conn = get_db_connection()
    if not conn:
        print("No connection.")
        return

    try:
        cur = conn.cursor()
        
        # 1. Asegurar que tablas existan (si no existen)
        print("Checking/Creating escuela_cursos...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_cursos (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                costo_matricula DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                costo_mensualidad DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                duracion_meses INTEGER NOT NULL DEFAULT 1,
                activo BOOLEAN DEFAULT TRUE
            );
        """)

        print("Checking/Creating escuela_grupos...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_grupos (
                id SERIAL PRIMARY KEY,
                codigo_grupo VARCHAR(50) NOT NULL UNIQUE,
                curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
                fecha_inicio DATE,
                activo BOOLEAN DEFAULT TRUE
            );
        """)
        
        # 2. Agregar columnas nuevas
        print("Migrating schema...")
        commands = [
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS dias_clase VARCHAR(200);",
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS hora_inicio TIME;",
            "ALTER TABLE escuela_grupos ADD COLUMN IF NOT EXISTS hora_fin TIME;"
        ]

        for cmd in commands:
            print(f"Executing: {cmd}")
            cur.execute(cmd)
            
        conn.commit()
        print("Migración EXITOSA.")
        
        # Verify columns
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'escuela_grupos'")
        cols = [c[0] for c in cur.fetchall()]
        print(f"Columnas finales en escuela_grupos: {cols}")

    except Exception:
        conn.rollback()
        traceback.print_exc()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_migration()
