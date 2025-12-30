import psycopg2
import sys
import json

def update_db_schema():
    print("Conectando a la base de datos...")
    try:
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",       
            password="jv123",
            database="jv_studio_pg_db"
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Actualizando tabla 'empleados'...")
        
        # 1. tipo_contrato
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN tipo_contrato VARCHAR(20) DEFAULT 'FIJO'")
            print("- Columna 'tipo_contrato' agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna 'tipo_contrato' ya existe.")
            
        # 2. puede_realizar_servicios
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN puede_realizar_servicios BOOLEAN DEFAULT FALSE")
            print("- Columna 'puede_realizar_servicios' agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna 'puede_realizar_servicios' ya existe.")

        # 3. porcentaje_comision_productos
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN porcentaje_comision_productos DECIMAL(5,2) DEFAULT 0.00")
            print("- Columna 'porcentaje_comision_productos' agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna 'porcentaje_comision_productos' ya existe.")
            
        # 4. configuracion_comision (JSONB)
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN configuracion_comision JSONB DEFAULT '{}'::jsonb")
            print("- Columna 'configuracion_comision' agregada.")
        except psycopg2.errors.DuplicateColumn:
            print("- Columna 'configuracion_comision' ya existe.")

        # 5. comision_servicios_default (Opcional, si queremos un % fijo por defecto)
        # Por ahora lo manejaremos dentro de configuracion_comision o seguiremos lógica separada.
        
        print("Migración completada exitosamente.")
        conn.close()
        
    except Exception as e:
        print(f"Error crítico: {e}")
        sys.exit(1)

if __name__ == "__main__":
    update_db_schema()
