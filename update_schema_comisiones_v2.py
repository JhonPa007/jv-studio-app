import psycopg2
import sys

def update_db_schema():
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",       
            password="jv123",
            database="jv_studio_pg_db"
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Updating table empleados...")
        
        # 1. tipo_contrato
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN tipo_contrato VARCHAR(20) DEFAULT 'FIJO'")
            print("- Column types_contrato added.")
        except psycopg2.errors.DuplicateColumn:
            print("- Column type_contrato already exists.")
            
        # 2. puede_realizar_servicios
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN puede_realizar_servicios BOOLEAN DEFAULT FALSE")
            print("- Column puede_realizar_servicios added.")
        except psycopg2.errors.DuplicateColumn:
            print("- Column puede_realizar_servicios already exists.")

        # 3. porcentaje_comision_productos
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN porcentaje_comision_productos DECIMAL(5,2) DEFAULT 0.00")
            print("- Column porcentaje_comision_productos added.")
        except psycopg2.errors.DuplicateColumn:
            print("- Column porcentaje_comision_productos already exists.")
            
        # 4. configuracion_comision (JSONB)
        try:
            cursor.execute("ALTER TABLE empleados ADD COLUMN configuracion_comision JSONB DEFAULT '{}'::jsonb")
            print("- Column configuracion_comision added.")
        except psycopg2.errors.DuplicateColumn:
            print("- Column configuracion_comision already exists.")

        print("Migration completed successfully.")
        conn.close()
        
    except Exception as e:
        # Avoid printing e directly if it has encoding issues in this environment
        print("Critical Error during migration.")
        print(repr(e))
        sys.exit(1)

if __name__ == "__main__":
    update_db_schema()
