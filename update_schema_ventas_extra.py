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
        
        print("Updating table ventas...")
        
        # Add es_hora_extra column
        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN es_hora_extra BOOLEAN DEFAULT FALSE")
            print("- Column es_hora_extra added to ventas.")
        except psycopg2.errors.DuplicateColumn:
            print("- Column es_hora_extra already exists in ventas.")
            
        print("Migration completed successfully.")
        conn.close()
        
    except Exception as e:
        print("Critical Error during migration.")
        print(repr(e))
        sys.exit(1)

if __name__ == "__main__":
    update_db_schema()
