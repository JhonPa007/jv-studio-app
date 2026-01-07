from app import create_app
from app.db import get_db
import psycopg2.extras

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'empleados';")
        columns = cursor.fetchall()
        print("Columns in 'empleados':")
        for col in columns:
            print(f"- {col['column_name']} ({col['data_type']})")
