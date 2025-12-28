from app.db import get_db
from app import create_app
from dotenv import load_dotenv
import os

load_dotenv() # Cargar variables de entorno

app = create_app()

with app.app_context():
    conn = get_db()
    cursor = conn.cursor()
    print("Creating table configuracion_sucursal...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_sucursal (
            id SERIAL PRIMARY KEY,
            sucursal_id INTEGER NOT NULL REFERENCES sucursales(id),
            agenda_intervalo VARCHAR(10) DEFAULT '00:15:00',
            agenda_color_bloqueo VARCHAR(20) DEFAULT '#ffecec',
            agenda_color_habilitado VARCHAR(20) DEFAULT '#ffffff',
            agenda_color_reserva VARCHAR(20) DEFAULT '#6c63ff',
            agenda_color_completado VARCHAR(20) DEFAULT '#198754',
            app_fuente VARCHAR(50) DEFAULT 'Inter',
            UNIQUE(sucursal_id)
        );
    """)
    conn.commit()
    print("Table created successfully.")
    conn.close()
