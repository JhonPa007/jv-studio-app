import psycopg2
import sys

def fix_db():
    print("Connecting to database...")
    try:
        # Credentials from db.py
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",       
            password="jv123",
            database="jv_studio_pg_db"
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Creating table 'horarios_extra'...")
        sql = """
            CREATE TABLE IF NOT EXISTS horarios_extra (
                id SERIAL PRIMARY KEY,
                empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
                sucursal_id INTEGER REFERENCES sucursales(id) ON DELETE CASCADE,
                fecha DATE NOT NULL,
                hora_inicio TIME NOT NULL,
                hora_fin TIME NOT NULL,
                motivo TEXT,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        cursor.execute(sql)
        print("Table 'horarios_extra' created/checked successfully.")
        
        conn.close()
        print("Done.")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    fix_db()
