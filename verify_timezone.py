from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    conn = get_db()
    with conn.cursor() as cursor:
        cursor.execute("SHOW TIME ZONE;")
        tz = cursor.fetchone()[0]
        print(f"Current Database Session Timezone: {tz}")
        
        cursor.execute("SELECT NOW();")
        now = cursor.fetchone()[0]
        print(f"Current Database Time: {now}")
