from check_ventas_cols import get_db_connection_params
import psycopg2

try:
    conn = psycopg2.connect(**get_db_connection_params())
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='gastos'")
    for row in cur.fetchall():
        print(row)
except Exception as e:
    print(e)
