
from app import create_app
from app.db import get_db
import psycopg2.extras
from dotenv import load_dotenv
import os

load_dotenv() # Load environment variables from .env

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("Checking configuration...")
        cursor.execute("SELECT * FROM configuracion_sistema WHERE id = 1")
        config = cursor.fetchone()
        
        if config:
            print("--- Current Configuration (ID=1) ---")
            for key, value in config.items():
                print(f"{key}: {value}")
            print("------------------------------------")
        else:
            print("❌ Configuration record (ID=1) NOT FOUND.")

    db.close()
