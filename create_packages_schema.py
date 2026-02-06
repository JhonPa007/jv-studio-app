
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_NAME = os.getenv('DB_NAME')
DB_USER = "postgres" # Using superuser to avoid permission issues
DB_PASS = os.getenv('DB_PASSWORD')
DB_PORT = os.getenv('DB_PORT')

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def run_migration():
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        
        print("Starting Service Packages Migration...")

        # 1. Create packages table
        print("Creating 'packages' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS packages (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Create package_items table
        print("Creating 'package_items' table...")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS package_items (
                package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
                service_id INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (package_id, service_id)
            );
        """)

        # 3. Add package_id to gift_cards table
        print("Updating 'gift_cards' table...")
        cur.execute("""
            ALTER TABLE gift_cards 
            ADD COLUMN IF NOT EXISTS package_id INTEGER REFERENCES packages(id) ON DELETE SET NULL;
        """)

        conn.commit()
        print("Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_migration()
