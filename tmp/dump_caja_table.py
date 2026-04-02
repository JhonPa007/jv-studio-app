from app.db import get_db
from app import create_app
app = create_app()
with app.app_context():
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'caja_sesiones'")
        columns = [r[0] for r in cursor.fetchall()]
        print(f"Columns in caja_sesiones: {columns}")
        cursor.execute("SELECT COUNT(*) FROM caja_sesiones")
        count = cursor.fetchone()[0]
        print(f"Total rows in caja_sesiones: {count}")
        cursor.execute("SELECT * FROM caja_sesiones WHERE estado = 'Abierta' LIMIT 5")
        rows = cursor.fetchall()
        print(f"Open sessions: {rows}")
