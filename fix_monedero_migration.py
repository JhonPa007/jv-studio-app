from app import create_app
from app.db import get_db
import sys
import psycopg2

sys.stdout.reconfigure(encoding='utf-8')

app = create_app()

with app.app_context():
    db = get_db()
    try:
        # DB connection is already established by get_db()
        # but get_db returns a connection object from g.db
        
        # We need to ensure we can commit
        db.autocommit = False # Flask usage usually commits explicitly or via transaction
        
        with db.cursor() as cur:
            # Check column
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
            if not cur.fetchone():
                print("Adding 'saldo_monedero' column...")
                try:
                    cur.execute("ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
                    db.commit()
                    print("✅ Column added successfully.")
                except Exception:
                    db.rollback()
                    import traceback
                    print(f"❌ Error adding column:\n{traceback.format_exc()}")
            else:
                print("ℹ️ Column 'saldo_monedero' already exists.")
                
    except Exception as e:
        print(f"❌ Script Error: {e}")
