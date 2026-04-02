import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def test_insert():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        with conn.cursor() as cur:
            sql = """
                INSERT INTO clientes (
                    tipo_documento, numero_documento, razon_social_nombres, apellidos, 
                    apellido_paterno, apellido_materno, fecha_nacimiento, 
                    direccion, email, telefono, ocupacion, fecha_registro
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
                RETURNING id
            """
            params = ('DNI', '99999999', 'Test Shamir', 'Test Cordova', 'Test', 'Cordova', None, None, None, '930989093', 'Test Ocupacion')
            cur.execute(sql, params)
            new_id = cur.fetchone()[0]
            print(f"Insertado ID: {new_id}")
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error test_insert: {e}")

if __name__ == "__main__":
    test_insert()
