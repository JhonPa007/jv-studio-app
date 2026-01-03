import psycopg2
import os

DB_HOST = "junction.proxy.rlwy.net"
DB_NAME = "railway"
DB_USER = "postgres"
DB_PASS = "LgsaPqjWwQzCqIisbHkK"
DB_PORT = "56029"

def migrate_points():
    try:
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            print(f"Conectando a {database_url.split('@')[1] if '@' in database_url else 'DATABASE_URL'}...")
            conn = psycopg2.connect(database_url)
        else:
            print("Usando credenciales locales (localhost)...")
            conn = psycopg2.connect(
                host="localhost",
                user="postgres",
                password="jv123",
                database="jv_studio_pg_db"
            )
        conn.autocommit = True
        cur = conn.cursor()

        print("Iniciando migración de puntos...")

        # 1. Sumar puntos_acumulados a puntos_fidelidad
        # Solo sumamos si puntos_acumulados > 0
        cur.execute("""
            UPDATE clientes 
            SET puntos_fidelidad = COALESCE(puntos_fidelidad, 0) + COALESCE(puntos_acumulados, 0)
            WHERE puntos_acumulados > 0;
        """)
        print(f"Puntos migrados. Filas afectadas: {cur.rowcount}")

        # 2. Resetear puntos_acumulados (opcional, para evitar doble conteo si se corre de nuevo erróneamente, 
        # aunque el código ya no lo usará)
        cur.execute("UPDATE clientes SET puntos_acumulados = 0 WHERE puntos_acumulados > 0;")
        print("Columna 'puntos_acumulados' reseteada a 0.")

        conn.close()
        print("Migración completada con éxito.")

    except Exception as e:
        print(f"Error durante la migración: {repr(e)}")

if __name__ == "__main__":
    migrate_points()
