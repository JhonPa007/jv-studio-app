from app.db import get_db
from app import create_app
app = create_app()
with app.app_context():
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'caja_sesiones'")
        print("Columns:")
        for r in cursor.fetchall():
            print(f"- {r[0]}")
