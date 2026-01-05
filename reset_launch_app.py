import os
import psycopg2
from dotenv import load_dotenv

# Cargar variables de entorno
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
print(f"Buscando .env en: {env_path}")
if os.path.exists(env_path):
    print("Archivo .env encontrado.")
    load_dotenv(env_path)
else:
    print("Archivo .env NO encontrado.")
    # Intenta cargar sin path especifico
    load_dotenv()

def get_db_connection():
    """Establece conexión con la base de datos."""
    database_url = os.environ.get('DATABASE_URL')
    print(f"DEBUG: DATABASE_URL is present: {bool(database_url)}")
    
    if not database_url:
        # Check components
        db_user = os.environ.get('DB_USER')
        db_pass = os.environ.get('DB_PASSWORD')
        print(f"DEBUG: DB_USER={db_user}, DB_PASSWORD={'*' * len(db_pass) if db_pass else 'None'}")
        
    if database_url:
        print(f"Conectando a: {database_url.split('@')[1] if '@' in database_url else 'DATABASE_URL'}")
        conn = psycopg2.connect(database_url)
    else:
        # Usar variables de entorno o defaults
        db_host = os.environ.get('DB_HOST', 'localhost')
        db_user = os.environ.get('DB_USER', 'postgres')
        db_pass = os.environ.get('DB_PASSWORD', 'jv123')
        db_name = os.environ.get('DB_NAME', 'jv_studio_pg_db')
        db_port = os.environ.get('DB_PORT', '5432')

        print(f"Conectando a {db_host} como usuario {db_user}...")
        conn = psycopg2.connect(
            host=db_host,
            user=db_user,
            password=db_pass,
            database=db_name,
            port=db_port
        )
    return conn

def reset_tables():
    """Limpia las tablas especificadas y reinicia sus contadores."""
    tables_to_reset = [
        "ausencias_empleado",
        "caja_sesiones",
        "comisiones",
        "compra_items",
        "compras",
        "gastos",
        "horarios_extra",
        "kardex",
        "movimientos_caja",
        "movimientos_fondo",
        "planillas",
        "propinas",
        "puntos_historial",
        "reservas",
        "venta_items",
        "venta_pagos",
        "ventas"
    ]

    conn = None
    log_file = "reset_result.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            print("Checkpoint 1: Conectado")
            f.write("Checkpoint 1: Conectado\n")
            
            # Get existing tables
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            existing_tables = {row[0] for row in cursor.fetchall()}
            
            valid_tables = []
            missing_tables = []
            
            for t in tables_to_reset:
                if t in existing_tables:
                    valid_tables.append(t)
                else:
                    missing_tables.append(t)

            msg = f"ATENCION: Se borraran TODOS los datos de {len(valid_tables)} tablas encontradas."
            print(msg)
            f.write(msg + "\n")
            
            if missing_tables:
                warn_msg = "AVISO: Las siguientes tablas solicitadas NO existen y seran ignoradas:"
                print(warn_msg)
                f.write(warn_msg + "\n")
                for t in missing_tables:
                    print(f" [SKIP] {t}")
                    f.write(f" [SKIP] {t}\n")
            
            if not valid_tables:
                print("No hay tablas validas para vaciar.")
                f.write("No hay tablas validas para vaciar.\n")
                return

            print("\nTablas a vaciar:")
            f.write("\nTablas a vaciar:\n")
            for t in valid_tables:
                print(f" - {t}")
                f.write(f" - {t}\n")
            
            print("Iniciando proceso...")
            f.write("Iniciando proceso...\n")

            tables_str = ", ".join(valid_tables)
            sql_query = f"TRUNCATE TABLE {tables_str} RESTART IDENTITY CASCADE;"
            
            print(f"Checkpoint 3: Executing SQL")
            f.write(f"Checkpoint 3: Executing SQL\n")
            
            try:
                cursor.execute(sql_query)
            except psycopg2.errors.InsufficientPrivilege as e:
                conn.rollback()
                err_msg = f"ERROR DE PERMISOS: {repr(e)}"
                print(err_msg)
                f.write(err_msg + "\n")
                print("Intentando vaciar tablas SIN reiniciar los contadores (identificadores)...")
                f.write("Intentando vaciar tablas SIN reiniciar los contadores (identificadores)...\n")
                
                # Retry without RESTART IDENTITY
                sql_retry = f"TRUNCATE TABLE {tables_str} CASCADE;"
                cursor = conn.cursor() # New cursor after rollback
                cursor.execute(sql_retry)
                print("⚠️ Tablas vaciadas, pero los IDs NO se reiniciaron (falta de permisos).")
                f.write("⚠️ Tablas vaciadas, pero los IDs NO se reiniciaron (falta de permisos).\n")
            
            print("Checkpoint 4: Executed")
            f.write("Checkpoint 4: Executed\n")
            
            conn.commit()
            success_msg = "EXITO: Tablas vaciadas y contadores reiniciados a cero."
            print(success_msg)
            f.write(success_msg + "\n")

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            err_msg = f"ERROR de Base de Datos: {repr(e)}"
            print(err_msg)
            try:
                f.write(err_msg + "\n")
            except:
                f.write(f"Error writing exception: {str(e).encode('utf-8', 'ignore')}\n")
            print("Intenta verificar si algun nombre de tabla es incorrecto.")
        except Exception as e:
            if conn:
                conn.rollback()
            err_msg = f"ERROR inesperado: {repr(e)}"
            print(err_msg)
            try:
                f.write(err_msg + "\n")
            except:
                pass
        finally:
            if conn:
                conn.close()
                print("Conexion cerrada.")

if __name__ == "__main__":
    reset_tables()
