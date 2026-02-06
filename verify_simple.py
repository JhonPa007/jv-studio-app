import psycopg2
from app.db import get_db
from flask import Flask
import sys

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev'

def verify_simple():
    with app.app_context():
        from dotenv import load_dotenv
        load_dotenv()
        db = get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.gift_cards');")
                result = cursor.fetchone()[0]
                if result:
                    print("VERIFICATION_SUCCESS")
                else:
                    print("VERIFICATION_FAILURE")
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    verify_simple()
