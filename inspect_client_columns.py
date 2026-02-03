import psycopg2
from app import create_app
from app.db import get_db
import sys

# Windows console encoding fix
sys.stdout.reconfigure(encoding='utf-8')

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'clientes';")
        columns = cur.fetchall()
        print("Columns in 'clientes' table:")
        found = False
        for col in columns:
            print(f"- {col[0]} ({col[1]})")
            if col[0] == 'saldo_monedero':
                found = True
        
        if found:
            print("\n✅ Column 'saldo_monedero' EXISTS.")
        else:
            print("\n❌ Column 'saldo_monedero' MISSING.")
