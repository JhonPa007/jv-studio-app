import psycopg2
from app.db import get_db
from app import create_app

app = create_app()

with app.app_context():
    try:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            tables = cursor.fetchall()
            print("--- TABLES ---")
            for t in tables:
                print(t[0])
    except Exception as e:
        print(f"Error: {e}")
