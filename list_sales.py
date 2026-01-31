
from app import create_app
from app.db import get_db
import psycopg2.extras
import sys
from dotenv import load_dotenv
import os

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("LISTING SALES:")
        cursor.execute("SELECT id, serie_comprobante, numero_comprobante, fecha_venta FROM ventas ORDER BY id DESC LIMIT 5")
        for row in cursor.fetchall():
            print(row)
