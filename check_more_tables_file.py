import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        with open('schema_output.txt', 'w') as f:
            for tbl in ['clientes', 'comisiones', 'venta_items', 'ventas', 'movimientos_caja', 'puntos_historial']:
                f.write(f"\n--- {tbl} ---\n")
                cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{tbl}';")
                cols = cur.fetchall()
                for col in cols:
                    f.write(f"  - {col['column_name']} ({col['data_type']})\n")
