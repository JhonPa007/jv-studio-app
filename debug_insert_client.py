import psycopg2
import psycopg2.extras
from app import create_app
from app.db import get_db

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Check all columns with their default values and nullable status
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'clientes'
        """)
        cols = cur.fetchall()
        for col in cols:
            print(f"{col['column_name']}: {col['data_type']}, Nullable: {col['is_nullable']}, Default: {col['column_default']}")
            
        # Try a test INSERT and catch the ACTUAL error for debugging
        try:
            print("\nAttempting test INSERT:")
            cur.execute("""
                    INSERT INTO clientes (razon_social_nombres, tipo_documento, numero_documento, direccion)
                    VALUES ('Clientes Varios', 'DNI', '00000000', '-')
                    RETURNING id
                """)
            new_id = cur.fetchone()['id']
            print(f"Success! Created ID: {new_id}")
            db.rollback() # Don't actually keep it for now
        except Exception as e:
            print(f"FAILED INSERT: {e}")
            db.rollback()
