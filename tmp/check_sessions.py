import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

def check_caja_sesiones():
    try:
        # Configuration is usually in config.py or env vars
        # Based on app/__init__.py, it uses Config
        # I'll try to get the DB URL from env if possible or just use what I find in db.py
        from app.db import get_db
        # But I need a flask app context...
        from app import create_app
        app = create_app()
        with app.app_context():
            db = get_db()
            with db.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM caja_sesiones WHERE estado = 'Abierta' ORDER BY fecha_apertura DESC")
                abiertas = cursor.fetchall()
                print(f"Sesiones abiertas: {len(abiertas)}")
                for s in abiertas:
                    print(f"ID: {s['id']}, Usuario: {s.get('usuario_id', s.get('usuario_apertura_id'))}, Sucursal: {s['sucursal_id']}, Fecha: {s.get('fecha_apertura', s.get('fecha_hora_apertura'))}, Estado: {s['estado']}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_caja_sesiones()
