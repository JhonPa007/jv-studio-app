import traceback
from app import create_app
from app.db import get_db
import psycopg2.extras
import os

app = create_app()
with app.app_context():
    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sql = """
            SELECT s.id, s.nombre, s.descripcion, s.duracion_minutos, s.precio, 
                   s.activo, cs.nombre as categoria_nombre, s.categoria_id, s.orden
            FROM servicios s
            JOIN categorias_servicios cs ON s.categoria_id = cs.id
            ORDER BY s.orden ASC, s.nombre ASC
        """
        print(f"Executing SQL:\n{sql}")
        cursor.execute(sql)
        res = cursor.fetchall()
        print(f"Success! Found {len(res)} services.")
    except Exception:
        print("Detailed Error Traceback:")
        traceback.print_exc()
