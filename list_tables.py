import os
import psycopg2
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

def list_tables():
    with open("tables_list.txt", "w", encoding="utf-8") as f:
        try:
            db_host = os.environ.get('DB_HOST', 'localhost')
            db_user = os.environ.get('DB_USER', 'postgres')
            db_pass = os.environ.get('DB_PASSWORD', 'jv123')
            db_name = os.environ.get('DB_NAME', 'jv_studio_pg_db')
            db_port = os.environ.get('DB_PORT', '5432')

            f.write(f"Connecting to {db_name} as {db_user}\n")
            conn = psycopg2.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=db_port
            )
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            
            tables = cursor.fetchall()
            f.write("Tables found:\n")
            for t in tables:
                f.write(f"- {t[0]}\n")
            
            conn.close()
        except Exception as e:
            f.write(f"Error: {repr(e)}\n")

if __name__ == "__main__":
    list_tables()
