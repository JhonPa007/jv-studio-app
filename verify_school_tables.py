
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
        except:
            pass
    
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
        print(f"Error: {e}")
        return None

def verify():
    conn = get_db_connection()
    if not conn:
        return

    cur = conn.cursor()
    tables = ['escuela_cursos', 'escuela_grupos', 'escuela_alumnos', 'escuela_pagos', 'escuela_cuotas']
    
    print("Verificando tablas creadas:")
    for table in tables:
        cur.execute(f"SELECT to_regclass('public.{table}');")
        result = cur.fetchone()[0]
        status = "EXISTE" if result else "NO EXISTE"
        print(f"Tabla {table}: {status}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    verify()
