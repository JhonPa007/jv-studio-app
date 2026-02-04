
from app.db import get_db
from app import create_app
import sys

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor() as cur:
        # Check numero_documento column in clientes
        cur.execute("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'clientes' AND column_name = 'numero_documento';")
        res = cur.fetchone()
        if res:
            print(f"Column: {res[0]}, Nullable: {res[1]}")
        else:
            print("Column 'numero_documento' not found in 'clientes'")
            
        # Also check constraints
        cur.execute("SELECT conname, contype FROM pg_constraint join pg_class on pg_constraint.conrelid = pg_class.oid where relname='clientes';")
        print("Constraints:")
        for row in cur.fetchall():
            print(f"{row[0]}: {row[1]}")
