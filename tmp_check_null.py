import psycopg2
import os
from dotenv import load_dotenv

load_dotenv('d:/JV_Studio/jv_studio_app/.env')

conn = psycopg2.connect(
    host=os.environ.get('DB_HOST', 'localhost'),
    user=os.environ.get('DB_USER', 'postgres'),
    password=os.environ.get('DB_PASSWORD', 'jv123'),
    database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
    port=os.environ.get('DB_PORT', '5432')
)
cursor = conn.cursor()
cursor.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name = 'gastos' AND column_name = 'caja_sesion_id'")
result = cursor.fetchone()
print(f"caja_sesion_id nullable: {result[0] if result else 'Not found'}")
cursor.close()
conn.close()
