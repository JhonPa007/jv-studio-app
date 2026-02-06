
from app import create_app
from app.db import get_db

app = create_app()

def force_create_packages():
    print("Initializing App Context...", flush=True)
    with app.app_context():
        db = get_db()
        try:
            with db.cursor() as cursor:
                print("Checking/Creating 'packages' table...", flush=True)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS packages (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                print("Checking/Creating 'package_items' table...", flush=True)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS package_items (
                        package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
                        service_id INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
                        quantity INTEGER NOT NULL DEFAULT 1,
                        PRIMARY KEY (package_id, service_id)
                    );
                """)

                print("Updating 'gift_cards' table...", flush=True)
                cursor.execute("""
                    ALTER TABLE gift_cards 
                    ADD COLUMN IF NOT EXISTS package_id INTEGER REFERENCES packages(id) ON DELETE SET NULL;
                """)
                
                db.commit()
                print("✅ SUCESS: Tables created/verified.", flush=True)
        except Exception as e:
            db.rollback()
            print(f"❌ ERROR: {e}", flush=True)

if __name__ == "__main__":
    force_create_packages()
