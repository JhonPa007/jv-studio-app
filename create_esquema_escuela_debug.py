
import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    conn = None
    if DATABASE_URL:
        print(f"Intentando conectar con DATABASE_URL...", flush=True)
        try:
            conn = psycopg2.connect(DATABASE_URL)
            print("Conectado con DATABASE_URL", flush=True)
            return conn
        except Exception as e:
            print(f"Falló DATABASE_URL: {e}", flush=True)
    
    print(f"Intentando conectar con variables de entorno (Host: {DB_HOST})...", flush=True)
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        print("Conectado con variables de entorno", flush=True)
        return conn
    except Exception as e:
        print(f"Falló conexión con variables: {e}", flush=True)
        return None

def create_schema():
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la BD.", flush=True)
        return

    try:
        cur = conn.cursor()
        print("Iniciando creación de esquema JV School (Español)...", flush=True)

        # 1. Tabla Cursos
        print("Creando tabla 'escuela_cursos'...", flush=True)
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

        # 2. Tabla Grupos
        print("Creando tabla 'escuela_grupos'...", flush=True)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_grupos (
                id SERIAL PRIMARY KEY,
                codigo_grupo VARCHAR(50) NOT NULL UNIQUE,
                curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
                fecha_inicio DATE,
                activo BOOLEAN DEFAULT TRUE
            );
        """)

        # 3. Tabla Alumnos
        print("Creando tabla 'escuela_alumnos'...", flush=True)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_alumnos (
                id SERIAL PRIMARY KEY,
                codigo_alumno VARCHAR(50) UNIQUE, 
                nombres VARCHAR(100) NOT NULL,
                apellidos VARCHAR(100),
                dni VARCHAR(20),
                telefono VARCHAR(20),
                curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
                grupo_id INTEGER REFERENCES escuela_grupos(id) ON DELETE SET NULL,
                fecha_inscripcion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_inicio_clases DATE,
                costo_matricula_acordado DECIMAL(10, 2),
                costo_mensualidad_acordada DECIMAL(10, 2),
                estado VARCHAR(20) DEFAULT 'Activo'
            );
        """)

        # 4. Tabla Pagos
        print("Creando tabla 'escuela_pagos'...", flush=True)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_pagos (
                id SERIAL PRIMARY KEY,
                alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
                monto DECIMAL(10, 2) NOT NULL,
                fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metodo_pago VARCHAR(50),
                usuario_id INTEGER,
                observaciones TEXT
            );
        """)

        # 5. Tabla Cuotas
        print("Creando tabla 'escuela_cuotas'...", flush=True)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_cuotas (
                id SERIAL PRIMARY KEY,
                alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
                concepto VARCHAR(100) NOT NULL,
                monto_original DECIMAL(10, 2) NOT NULL,
                monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
                saldo DECIMAL(10, 2) DEFAULT 0.00,
                fecha_vencimiento DATE,
                estado VARCHAR(20) DEFAULT 'Pendiente',
                orden_pago INTEGER DEFAULT 0
            );
        """)

        conn.commit()
        print("¡Esquema creado exitosamente y COMMITTED!", flush=True)

    except Exception as e:
        conn.rollback()
        with open("creation_error.log", "w") as f:
            f.write(f"Error creando esquema: {e}\n")
            f.write(f"Tipo de error: {type(e)}\n")
        print(f"Error creando esquema: {e}", flush=True)
    finally:
        if cur: cur.close()
        if conn: conn.close()

if __name__ == "__main__":
    create_schema()
