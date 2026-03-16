
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def check_gastos_and_caja():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "jv_studio_pg_db"),
            user=os.getenv("DB_USER", "jv_user"),
            password=os.getenv("DB_PASSWORD", "jv123"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Check columns in gastos
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'gastos'")
            cols = [c['column_name'] for c in cur.fetchall()]
            print(f"Columns in gastos: {cols}")
            
            # 2. Check recent gastost with NULL caja
            query = "SELECT id, sucursal_id, caja_sesion_id, descripcion, monto"
            if 'estado_confirmacion' in cols:
                query += ", estado_confirmacion"
            query += " FROM gastos WHERE categoria_gasto_id IN (SELECT id FROM categorias_gastos WHERE nombre ILIKE '%adelanto%') ORDER BY id DESC LIMIT 5"
            
            cur.execute(query)
            rows = cur.fetchall()
            print("Recent adelantos:")
            for row in rows:
                print(row)
                
            # 3. Check for open cajas in sucursal 1 (common in screenshot)
            cur.execute("SELECT id, sucursal_id, estado, usuario_id FROM caja_sesiones WHERE sucursal_id = 1 AND estado = 'Abierta'")
            cajas = cur.fetchall()
            print(f"Open cajas in sucursal 1: {cajas}")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_gastos_and_caja()
