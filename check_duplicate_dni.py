import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM clientes WHERE numero_documento = '00000000'")
        rows = cur.fetchall()
        print(f"CLIENTS WITH DNI 00000000: {len(rows)}")
        for r in rows:
            print(r)
