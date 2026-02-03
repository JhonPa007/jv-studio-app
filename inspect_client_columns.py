
import psycopg2
from app.db import get_db_connection
from flask import Flask

app = Flask(__name__)

with app.app_context():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'clientes';")
    columns = cur.fetchall()
    print("Columns in 'clientes' table:")
    for col in columns:
        print(f"- {col[0]} ({col[1]})")
    conn.close()
