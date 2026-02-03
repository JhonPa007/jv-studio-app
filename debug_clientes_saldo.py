from app import create_app
from app.db import get_db
import psycopg2.extras
import sys

# Set encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

app = create_app()

with app.app_context():
    db = get_db()
    try:
        # Use RealDictCursor to mimic routes.py
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            print("--- Executing Query ---")
            cursor.execute("""
                SELECT id, razon_social_nombres, apellidos, telefono, numero_documento,
                       TO_CHAR(fecha_nacimiento, 'YYYY-MM-DD') as fecha_nac_str,
                       cumpleanos_validado, rechazo_dato_cumpleanos,
                       saldo_monedero
                FROM clientes 
                WHERE telefono = '983000102'
            """)
            client = cursor.fetchone()
            
            if client:
                print(f"Client Found: {client['razon_social_nombres']}")
                print(f"Saldo Key Present: {'saldo_monedero' in client}")
                print(f"Saldo Value: {client.get('saldo_monedero')}")
                print(f"Saldo Type: {type(client.get('saldo_monedero'))}")
            else:
                print("Client '983000102' not found via Python Query.")
                
    except Exception as e:
        print(f"Error: {e}")
