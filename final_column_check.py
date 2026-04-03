import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Check columns of venta_items
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'venta_items'")
        cols = [r['column_name'] for r in cur.fetchall()]
        print(f"Columns in 'venta_items': {cols}")
        
        # Check columns of comisiones
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'comisiones'")
        cols = [r['column_name'] for r in cur.fetchall()]
        print(f"Columns in 'comisiones': {cols}")
