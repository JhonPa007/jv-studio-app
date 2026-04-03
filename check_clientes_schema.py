import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'clientes';")
        cols = cur.fetchall()
        print("CLIENTES COLUMNS:")
        for col in cols:
            print(f"  - {col['column_name']} ({col['data_type']})")
        
        cur.execute("SELECT * FROM clientes WHERE razon_social_nombres = 'Clientes Varios' LIMIT 1")
        res = cur.fetchone()
        print("\nCLIENTES VARIOS RECORD:")
        print(res)
