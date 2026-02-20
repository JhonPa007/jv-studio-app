import psycopg2
import os
# from dotenv import load_dotenv

# load_dotenv() 

def force_admin():
    try:
        # Hardcode postgres user/pass based on config defaults
        print("Connecting as postgres...")
        conn = psycopg2.connect(
            host='localhost', # Hardcoded default
            user='postgres',
            password='jv123',
            database='jv_studio_pg_db', # Hardcoded default
            port='5432'
        )
        cursor = conn.cursor()
        
        # Read SQL with LATIN-1
        print("Reading SQL file as latin-1...")
        with open('crear_tablas_escuela.sql', 'r', encoding='latin-1') as f:
            sql_script = f.read()
            
        print("Executing SQL script as postgres...")
        cursor.execute(sql_script)
        conn.commit()
        print("Committed.")
        
        # Verify
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'escuela_%'")
        tables = cursor.fetchall()
        
        with open('schema_result_admin.txt', 'w') as f:
            f.write("Tables found (admin run):\n")
            for t in tables:
                f.write(f"- {t[0]}\n")
            if len(tables) >= 5:
                f.write("SUCCESS: School tables created.\n")
            else:
                f.write("FAILURE: School tables missing.\n")

        # Grant privileges to 'jv_user'
        try:
             cursor.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO jv_user;")
             cursor.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO jv_user;")
             conn.commit()
             print("Granted privileges to jv_user.")
        except Exception as e:
             print(f"Could not grant privileges: {e}")

        cursor.close()
        conn.close()
        
    except Exception as e:
        with open('schema_result_admin.txt', 'w') as f:
            f.write(f"ERROR: {e}\n")
        print(f"Error: {e}")

if __name__ == "__main__":
    force_admin()
