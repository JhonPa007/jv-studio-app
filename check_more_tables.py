import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for tbl in ['comisiones', 'venta_items', 'ventas', 'movimientos_caja', 'puntos_historial']:
            print(f"\n--- {tbl} ---")
            cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{tbl}';")
            cols = cur.fetchall()
            for col in cols:
                print(f"  - {col['column_name']} ({col['data_type']})")
