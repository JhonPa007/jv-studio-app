
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except Exception as e:
            print(f"Error conectando vía DATABASE_URL: {e}")
            return None
    
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error conectando a la base de datos: {e}")
        return None

def create_schema():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        print("Iniciando creación de esquema JV School (Español)...")

        # 1. Tabla Cursos
        print("Creando tabla 'escuela_cursos'...")
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
        print("Creando tabla 'escuela_grupos'...")
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
        # Nota: student_code lo generaremos por software o trigger, aquí definimos la columna.
        print("Creando tabla 'escuela_alumnos'...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_alumnos (
                id SERIAL PRIMARY KEY,
                codigo_alumno VARCHAR(50) UNIQUE, 
                nombres VARCHAR(100) NOT NULL,
                dni VARCHAR(20),
                telefono VARCHAR(20),
                curso_id INTEGER REFERENCES escuela_cursos(id) ON DELETE SET NULL,
                grupo_id INTEGER REFERENCES escuela_grupos(id) ON DELETE SET NULL,
                fecha_inscripcion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fecha_inicio_clases DATE,
                costo_matricula_acordado DECIMAL(10, 2), -- Por si difiere del default del curso
                costo_mensualidad_acordada DECIMAL(10, 2), -- Por si difiere del default
                estado VARCHAR(20) DEFAULT 'Activo' -- Activo, Retirado, Egresado
            );
        """)

        # 4. Tabla Pagos (Historial de ingresos)
        print("Creando tabla 'escuela_pagos'...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_pagos (
                id SERIAL PRIMARY KEY,
                alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
                monto DECIMAL(10, 2) NOT NULL,
                fecha_pago TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metodo_pago VARCHAR(50), -- Efectivo, Yape, etc.
                usuario_id INTEGER, -- Quién registró el pago (opcional, referencia a empleados)
                observaciones TEXT
            );
        """)

        # 5. Tabla Cuotas (Matrícula, Mensualidad 1, etc.)
        # Esta tabla rastrea el ESTADO de cada deuda.
        print("Creando tabla 'escuela_cuotas'...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS escuela_cuotas (
                id SERIAL PRIMARY KEY,
                alumno_id INTEGER REFERENCES escuela_alumnos(id) ON DELETE CASCADE,
                concepto VARCHAR(100) NOT NULL, -- 'Matrícula', 'Mensualidad 1', etc.
                monto_original DECIMAL(10, 2) NOT NULL,
                monto_pagado DECIMAL(10, 2) DEFAULT 0.00,
                saldo DECIMAL(10, 2) DEFAULT 0.00,
                fecha_vencimiento DATE,
                estado VARCHAR(20) DEFAULT 'Pendiente', -- Pendiente, Parcial, Completo
                orden_pago INTEGER DEFAULT 0 -- Para ordenar la cascada de pagos (0=Matrícula, 1=Mes 1...)
            );
        """)

        conn.commit()
        print("¡Esquema creado exitosamente!")

    except Exception as e:
        conn.rollback()
        print(f"Error creando esquema: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    create_schema()
