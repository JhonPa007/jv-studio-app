from app import create_app
from app.db import get_db

app = create_app()
with app.app_context():
    db = get_db()
    print("Schema updated (if necessary).")
