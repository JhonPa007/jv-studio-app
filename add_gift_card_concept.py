
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
os.environ['PGCLIENTENCODING'] = 'UTF8'

def migrate():
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        
        # Add 'concept' column to gift_cards
        print("Checking/Adding 'concept' column to gift_cards...")
        cur.execute("ALTER TABLE gift_cards ADD COLUMN IF NOT EXISTS concept VARCHAR(255);")
        
        conn.commit()
        print("Migration successful.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    migrate()
