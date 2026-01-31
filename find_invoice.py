
from app import create_app
from app.db import get_db
import psycopg2.extras
from dotenv import load_dotenv
import os
import sys

# Force UTF-8 encoding for stdout
sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("SEARCHING_START")
        cursor.execute("SELECT id, serie_comprobante, numero_comprobante FROM ventas WHERE serie_comprobante = 'F001' AND numero_comprobante = 2")
        venta = cursor.fetchone()
        
        if venta:
            print(f"FOUND: ID={venta['id']}")
        else:
            print("NOT_FOUND")
            cursor.execute("SELECT serie_comprobante, MAX(numero_comprobante) FROM ventas GROUP BY serie_comprobante")
            res = cursor.fetchall()
            print(f"MAX_NUMBERS: {res}")
            
    db.close()
