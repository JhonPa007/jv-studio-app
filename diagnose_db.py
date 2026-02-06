import psycopg2
from app.db import get_db
from flask import Flask
from dotenv import load_dotenv
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev'

def diagnose():
    print("🚑 Diagnosing Database...")
    load_dotenv()
    
    print(f"Env DB_NAME: {os.environ.get('DB_NAME')}")
    print(f"Env DB_PORT: {os.environ.get('DB_PORT')}")
    
    with app.app_context():
        db = get_db()
        if not db:
            print("❌ No connection.")
            return

        try:
            with db.cursor() as cursor:
                # Get current DB name
                cursor.execute("SELECT current_database();")
                db_name = cursor.fetchone()[0]
                print(f"📚 Connected to Database: {db_name}")
                
                # Get current User
                cursor.execute("SELECT current_user;")
                user = cursor.fetchone()[0]
                print(f"👤 User: {user}")

                # List all tables in public schema
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public';
                """)
                tables = cursor.fetchall()
                print(f"📊 Found {len(tables)} tables:")
                found = False
                for t in tables:
                    name = t[0]
                    if name == 'gift_cards':
                        print(f"   ✅ {name} <--- FOUND IT!")
                        found = True
                    else:
                        print(f"   - {name}")
                
                if not found:
                    print("❌ 'gift_cards' NOT FOUND in table list.")

        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    diagnose()
