
import psycopg2

def fix_table():
    log_file = "db_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("Starting fix_loyalty_table (File Log)...\n")
        conn = None
        try:
            f.write("Connecting...\n")
            conn = psycopg2.connect(
                host="localhost",
                user="postgres",       
                password="jv123",
                database="jv_studio_pg_db"
            )
            f.write("Connected.\n")
            cur = conn.cursor()
            
            # Check dependencies
            f.write("Checking loyalty_rules...\n")
            cur.execute("SELECT to_regclass('loyalty_rules')")
            res = cur.fetchone()[0]
            f.write(f"loyalty_rules exists: {res}\n")
            
            if not res:
                f.write("FATAL: loyalty_rules missing. Creating it...\n")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS loyalty_rules (
                        id SERIAL PRIMARY KEY,
                        nombre VARCHAR(100) NOT NULL,
                        servicio_id INTEGER REFERENCES servicios(id),
                        cantidad_requerida INTEGER NOT NULL,
                        periodo_meses INTEGER NOT NULL,
                        descuento_porcentaje NUMERIC(5, 2) NOT NULL,
                        activo BOOLEAN DEFAULT TRUE
                    );
                """)
                f.write("Created loyalty_rules.\n")

            f.write("Creating loyalty_rule_services...\n")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_rule_services (
                    loyalty_rule_id INTEGER REFERENCES loyalty_rules(id) ON DELETE CASCADE,
                    servicio_id INTEGER REFERENCES servicios(id) ON DELETE CASCADE,
                    PRIMARY KEY (loyalty_rule_id, servicio_id)
                );
            """)
            
            conn.commit()
            f.write("Fix Success: loyalty_rule_services created.\n")
            
        except Exception as e:
            f.write(f"Fix Failed: {e}\n")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    fix_table()
