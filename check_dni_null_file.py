
from app.db import get_db
from app import create_app
import sys

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor() as cur:
        with open('d:\\JV_Studio\\jv_studio_app\\dni_status.txt', 'w') as f:
            # Check numero_documento column in clientes
            cur.execute("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'clientes' AND column_name = 'numero_documento';")
            res = cur.fetchone()
            if res:
                f.write(f"Column: {res[0]}, Nullable: {res[1]}\n")
            else:
                f.write("Column 'numero_documento' not found in 'clientes'\n")
            
            # Also check constraints
            cur.execute("SELECT conname, contype FROM pg_constraint join pg_class on pg_constraint.conrelid = pg_class.oid where relname='clientes';")
            f.write("Constraints:\n")
            for row in cur.fetchall():
                f.write(f"{row[0]}: {row[1]}\n")
