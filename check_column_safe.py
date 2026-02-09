
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
os.environ['PGCLIENTENCODING'] = 'UTF8'

def check():
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST'),
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD'),
            database=os.environ.get('DB_NAME'),
            port=os.environ.get('DB_PORT')
        )
        cur = conn.cursor()
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
        if cur.fetchone():
            print("EXISTS")
        else:
            print("MISSING")
        conn.close()
    except Exception as e:
        # Avoid printing unicode error
        try:
             print(f"ERROR: {e}")
        except:
             print("ERROR: (unicode)")

if __name__ == "__main__":
    check()
