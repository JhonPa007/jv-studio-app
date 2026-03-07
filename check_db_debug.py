import psycopg2
import os
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv('d:/JV_Studio/jv_studio_app/.env')

conn = psycopg2.connect(
    host=os.environ.get('DB_HOST', 'localhost'),
    user=os.environ.get('DB_USER', 'postgres'),
    password=os.environ.get('DB_PASSWORD', 'jv123'),
    database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
    port=os.environ.get('DB_PORT', '5432')
)
# Use DictCursor for easier inspection
cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

print("--- Categorias de Gastos ---")
cursor.execute("SELECT id, nombre FROM categorias_gastos WHERE id IN (4, 5)")
for row in cursor.fetchall():
    print(dict(row))

print("\n--- Estado de Confirmación para IDs 160, 161, 162 ---")
# Check if column exists first to avoid error if migration failed
cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos' AND column_name = 'estado_confirmacion'")
if cursor.fetchone():
    cursor.execute("SELECT id, descripcion, caja_sesion_id, estado_confirmacion FROM gastos WHERE id IN (160, 161, 162)")
    for row in cursor.fetchall():
        print(dict(row))
else:
    print("Column 'estado_confirmacion' DOES NOT EXIST in 'gastos' table!")

cursor.close()
conn.close()
