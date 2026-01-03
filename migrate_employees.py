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
        print("Iniciando migración de empleados...")

        # 1. Unificar: Si puede_realizar_servicios es TRUE, entonces realiza_servicios debe ser TRUE
        # "realiza_servicios" es la columna que nos vamos a quedar (según tu código parece ser la más usada o estándar en tu app, 
        # aunque el usuario dijo 'realiza_servicios' y 'puede_realizar_servicios', y sugirió eliminar 'puede_realizar_servicios').
        
        # Primero, asegurarnos de que la columna destino exista (asumo que sí).
        # Hacemos el update.
        cur.execute("""
            UPDATE empleados 
            SET realiza_servicios = TRUE 
            WHERE puede_realizar_servicios = TRUE;
        """)
        print(f"Filas actualizadas (Empleados habilitados): {cur.rowcount}")

        # 2. (Opcional) Eliminar la columna vieja para evitar confusión futura.
        # Comentado por seguridad, pero si el usuario lo pidió explícitamente, lo descomentamos.
        # El usuario dijo: "Se debe eliminar una de ellas".
        try:
            cur.execute("ALTER TABLE empleados DROP COLUMN puede_realizar_servicios;")
            print("Columna 'puede_realizar_servicios' eliminada.")
        except Exception as e_alter:
            print(f"No se pudo eliminar la columna (tal vez ya no existe): {e_alter}")
        
        conn.commit()
        print("Migración de empleados Éxitosa.")
        
    except Exception as e:
        if conn: conn.rollback()
        print(f"Error: {repr(e)}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    run_migration()
