import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    port=os.getenv('DB_PORT')
)

try:
    cur = conn.cursor()
    # Add column if not exists
    cur.execute("""
        ALTER TABLE gastos 
        ADD COLUMN IF NOT EXISTS estado_confirmacion VARCHAR(20) DEFAULT 'Pendiente'
    """)
    # Set existing ones to Confirmado to not break history
    cur.execute("""
        UPDATE gastos 
        SET estado_confirmacion = 'Confirmado'
        WHERE estado_confirmacion = 'Pendiente'
    """)
    conn.commit()
    print("Migration successful: Added estado_confirmacion to gastos.")
except Exception as e:
    conn.rollback()
    print("Migration failed:", e)
finally:
    if conn:
        conn.close()
