
import os
import psycopg2
import psycopg2.extras

def check_latest_ventas():
    conn = psycopg2.connect(
        dbname="jv_studio_pg_db",
        user="jv_user",
        password="jv123",
        host="localhost",
        port="5432"
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, serie_comprobante, numero_comprobante, tipo_comprobante FROM ventas ORDER BY id DESC LIMIT 5")
            ventas = cur.fetchall()
            for v in ventas:
                print(v)
    finally:
        conn.close()

if __name__ == "__main__":
    check_latest_ventas()
