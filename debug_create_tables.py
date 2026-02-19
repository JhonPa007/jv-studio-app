import psycopg2
import os
import traceback
import sys
from dotenv import load_dotenv

# Redirect stderr to a file
sys.stderr = open('error.log', 'w')

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')
DATABASE_URL = os.getenv('DATABASE_URL')

def create_tables():
    config = {
        'host': DB_HOST,
        'database': DB_NAME,
        'user': DB_USER,
        'password': DB_PASS,
        'port': DB_PORT
    }
    
    try:
        conn = psycopg2.connect(**config)
        cur = conn.cursor()
        
        print("Dropping test_table if exists...", file=sys.stdout)
        cur.execute("DROP TABLE IF EXISTS test_table")
        
        print("Creating test_table...", file=sys.stdout)
        cur.execute("CREATE TABLE test_table (id SERIAL PRIMARY KEY)")
        
        print("Creating escuela_cursos without IF NOT EXISTS...", file=sys.stdout)
        # Drop first to be clean
        cur.execute("DROP TABLE IF EXISTS escuela_grupos") # Dependent
        cur.execute("DROP TABLE IF EXISTS escuela_cursos")
        
        cur.execute("""
            CREATE TABLE escuela_cursos (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                costo_matricula DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                costo_mensualidad DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                duracion_meses INTEGER NOT NULL DEFAULT 1,
                activo BOOLEAN DEFAULT TRUE
            )
        """)
        
        print("Creating escuela_grupos without IF NOT EXISTS...", file=sys.stdout)
        cur.execute("""
            CREATE TABLE escuela_grupos (
                id SERIAL PRIMARY KEY,
                codigo_grupo VARCHAR(50) NOT NULL UNIQUE,
                curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
                fecha_inicio DATE,
                dias_clase VARCHAR(200),
                hora_inicio TIME,
                hora_fin TIME,
                activo BOOLEAN DEFAULT TRUE
            )
        """)
        
        conn.commit()
        print("Success!", file=sys.stdout)
        conn.close()
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    create_tables()
