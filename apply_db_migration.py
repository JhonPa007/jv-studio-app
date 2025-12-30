from app import create_app
from app.db import get_db
import psycopg2

app = create_app()

def migrate():
    with app.app_context():
        print("Obteniendo conexion DB via app context...")
        conn = get_db()
        if not conn:
            print("No se pudo obtener conexion (get_db retorno None).")
            return
            
        print("Iniciando migracion de esquema para comisiones...")
        # Ensure autocommit is on for DDL, or commit manually
        # get_db returns a connection. In Flask typically we rely on request teardown or manual commit.
        # But for DDL, autocommit is often safer or required.
        old_autocommit = conn.autocommit
        conn.autocommit = True
        
        cursor = conn.cursor()
        
        # 1. tipo_contrato
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN tipo_contrato VARCHAR(20) DEFAULT 'FIJO'")
            print("- Columna tipo_contrato agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna tipo_contrato ya existe.")
        except Exception as e:
            print(f"Error agregando tipo_contrato: {e}")
            
        # 2. puede_realizar_servicios
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN puede_realizar_servicios BOOLEAN DEFAULT FALSE")
            print("- Columna puede_realizar_servicios agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna puede_realizar_servicios ya existe.")
        except Exception as e:
            print(f"Error agregando puede_realizar_servicios: {e}")

        # 3. porcentaje_comision_productos
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN porcentaje_comision_productos DECIMAL(5,2) DEFAULT 0.00")
            print("- Columna porcentaje_comision_productos agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna porcentaje_comision_productos ya existe.")
        except Exception as e:
            print(f"Error agregando porcentaje_comision_productos: {e}")
            
        # 4. configuracion_comision (JSONB)
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN configuracion_comision JSONB DEFAULT '{}'::jsonb")
            print("- Columna configuracion_comision agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna configuracion_comision ya existe.")
        except Exception as e:
            print(f"Error agregando configuracion_comision: {e}")
            
        print("Migracion completada.")
        
        # Restore autocommit
        conn.autocommit = old_autocommit

if __name__ == "__main__":
    migrate()
