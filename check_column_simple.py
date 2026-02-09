
import os
import psycopg2
import sys

def check_column():
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
        if cur.fetchone():
            print("EXISTS")
        else:
            print("MISSING")
        conn.close()
    except Exception as e:
        print("ERROR")

if __name__ == "__main__":
    check_column()
