
import psycopg2

def run():
    with open("log_final.txt", "w") as f:
        try:
            conn = psycopg2.connect(
                host="localhost", 
                user="postgres", 
                password="jv123", 
                database="jv_studio_pg_db"
            )
            cur = conn.cursor()
            # Check
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='venta_items' AND column_name='loyalty_consumption_group_id'")
            if cur.fetchone():
                f.write("Exists\n")
            else:
                f.write("Adding...\n")
                cur.execute("ALTER TABLE venta_items ADD COLUMN loyalty_consumption_group_id VARCHAR(50)")
                conn.commit()
                f.write("Added\n")
        except Exception as e:
            f.write(str(e))
        finally:
            if conn: conn.close()

if __name__ == "__main__":
    run()
