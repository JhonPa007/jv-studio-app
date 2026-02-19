import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask
from app.db import get_db
import os
from app import create_app

app = create_app()

with app.app_context():
    try:
        db = get_db()
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            print("--- CURSOS ---")
            cursor.execute("SELECT * FROM escuela_cursos")
            cursos = cursor.fetchall()
            if not cursos:
                print("No courses found.")
            else:
                for c in cursos:
                    print(dict(c))

            print("\n--- GRUPOS ---")
            cursor.execute("SELECT * FROM escuela_grupos")
            grupos = cursor.fetchall()
            if not grupos:
                print("No groups found.")
            else:
                for g in grupos:
                    print(dict(g))
                    
    except Exception as e:
        print(f"Error: {e}")
