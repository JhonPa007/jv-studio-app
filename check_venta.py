
import os
import psycopg2
import psycopg2.extras

def check_venta(venta_id):
    conn = psycopg2.connect(
        dbname="jv_studio_pg_db",
        user="jv_user",
        password="jv123",
        host="localhost",
        port="5432"
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, serie_comprobante, numero_comprobante, tipo_comprobante FROM ventas WHERE id = %s", (venta_id,))
            venta = cur.fetchone()
            print(f"Venta ID {venta_id}: {venta}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_venta(624)
