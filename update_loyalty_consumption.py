
import psycopg2

def add_consumption_column():
    log_file = "migration_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("Iniciando migración...\n")
        conn = None
        try:
            conn = psycopg2.connect(
                host="localhost",
                user="postgres",       
                password="jv123",
                database="jv_studio_pg_db"
            )
            cur = conn.cursor()
            
            f.write("Verificando columna...\n")
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='venta_items' AND column_name='loyalty_consumption_group_id';
            """)
            if cur.fetchone():
                f.write("La columna ya existe.\n")
            else:
                f.write("Agregando columna...\n")
                cur.execute("""
                    ALTER TABLE venta_items 
                    ADD COLUMN loyalty_consumption_group_id VARCHAR(50);
                """)
                conn.commit()
                f.write("Columna agregada exitosamente.\n")
                
        except Exception as e:
            f.write(f"Error: {e}\n")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    add_consumption_column()
