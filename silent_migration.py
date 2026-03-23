import os
from dotenv import load_dotenv
import psycopg2

def migrate():
    load_dotenv('.env')
    try:
        # Prioritize env vars over .env for this run
        user = os.environ.get('DB_USER_FORCE', 'postgres')
        pwd = os.environ.get('DB_PASSWORD_FORCE', 'jv123')
        
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=user,
            password=pwd,
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        conn.autocommit = True
        with conn.cursor() as cursor:
            for table in ['servicios', 'productos']:
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN orden INTEGER DEFAULT 0")
                    print(f"Added {table}.orden")
                except Exception as e:
                    pass # already exists or other error
        conn.close()
        print("Migration attempt finished")
    except Exception as e:
        pass # silent

if __name__ == "__main__":
    migrate()
