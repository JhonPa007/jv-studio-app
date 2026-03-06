import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        database=os.getenv('DB_NAME', 'jv_studio_pg_db'),
        user='postgres',
        password=os.getenv('DB_PASSWORD', 'jv123'),
        port=os.getenv('DB_PORT', '5432')
    )
    cur = conn.cursor()
    # Otorgar permisos al usuario jv_user
    cur.execute("GRANT ALL PRIVILEGES ON TABLE gastos TO jv_user;")
    
    # Agregar la columna
    cur.execute("""
        ALTER TABLE gastos 
        ADD COLUMN IF NOT EXISTS estado_confirmacion VARCHAR(20) DEFAULT 'Pendiente'
    """)
    cur.execute("""
        UPDATE gastos 
        SET estado_confirmacion = 'Confirmado'
        WHERE estado_confirmacion = 'Pendiente' OR estado_confirmacion IS NULL
    """)
    conn.commit()
    print("Migration successful: Added estado_confirmacion to gastos.")
except Exception as e:
    if 'conn' in locals():
        conn.rollback()
    print("Migration failed:", e)
finally:
    if 'conn' in locals():
        conn.close()
