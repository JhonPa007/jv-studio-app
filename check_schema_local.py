from app import create_app
from app.db import get_db
import psycopg2.extras

app = create_app()
with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'productos'")
        columns = cursor.fetchall()
        print("Columns in 'productos':")
        for col in columns:
            print(f"- {col['column_name']}")
        
        cursor.execute("SELECT * FROM information_schema.tables WHERE table_name = 'marcas'")
        if cursor.fetchone():
            print("\nTable 'marcas' exists.")
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'marcas'")
            m_cols = cursor.fetchall()
            for col in m_cols:
                print(f"  - {col['column_name']}")
        else:
            print("\nTable 'marcas' does NOT exist.")
