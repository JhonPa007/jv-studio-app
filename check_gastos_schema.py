from app import create_app
from app.db import get_db
import psycopg2.extras

app = create_app()
with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("Checking 'gastos' columns:")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos'")
        for col in cursor.fetchall():
            print(f"- {col['column_name']}")
            
        print("\nChecking 'categorias_gastos' columns:")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'categorias_gastos'")
        for col in cursor.fetchall():
            print(f"- {col['column_name']}")
