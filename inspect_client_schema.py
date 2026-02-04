
from app.db import get_db
from flask import Flask
import os
from app import create_app

app = create_app()

with app.app_context():
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT column_name, is_nullable, data_type FROM information_schema.columns WHERE table_name = 'clientes';")
        columns = cur.fetchall()
        print(f"Columns in 'clientes' table:")
        for col in columns:
            print(f"Name: {col[0]}, Nullable: {col[1]}, Type: {col[2]}")
    except Exception as e:
        print(f"Error: {e}")
