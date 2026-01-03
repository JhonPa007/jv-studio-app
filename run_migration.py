import psycopg2
import os

def run_migration():
    conn = None
    try:
        url = os.environ.get('DATABASE_URL')
        if url:
             conn = psycopg2.connect(url)
             print(f"Conectado a NUBE/URL: {url.split('@')[1] if '@' in url else '...'}")
        else:
             print("Usando credenciales locales (localhost)...")
             conn = psycopg2.connect(host="localhost", user="postgres", password="jv123", database="jv_studio_pg_db")

        cur = conn.cursor()
        print("Iniciando migración...")

        # 1. Sumar
        cur.execute("""
            UPDATE clientes 
            SET puntos_fidelidad = COALESCE(puntos_fidelidad, 0) + COALESCE(puntos_acumulados, 0)
            WHERE puntos_acumulados > 0;
        """)
        print(f"Filas actualizadas (Suma): {cur.rowcount}")

        # 2. Resetear
        cur.execute("UPDATE clientes SET puntos_acumulados = 0 WHERE puntos_acumulados > 0;")
        print(f"Filas actualizadas (Reset): {cur.rowcount}")
        
        conn.commit()
        print("Migración Éxitosa.")
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error: {repr(e)}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_migration()
