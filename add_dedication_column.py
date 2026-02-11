import psycopg2
from app.db import get_db
from app import create_app

app = create_app()

with app.app_context():
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("ALTER TABLE gift_cards ADD COLUMN IF NOT EXISTS dedicatoria TEXT")
            db.commit()
            print("Successfully added 'dedicatoria' column to 'gift_cards' table.")
    except Exception as e:
        db.rollback()
        print(f"Error adding column: {e}")
