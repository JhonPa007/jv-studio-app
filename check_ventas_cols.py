
import psycopg2
import os
from app.routes import get_db_connection_params

def check_columns():
    try:
        conn = psycopg2.connect(**get_db_connection_params())
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'ventas'
        """)
        rows = cur.fetchall()
        print("Columns in 'ventas' table:")
        for r in rows:
            print(f"- {r[0]} ({r[1]})")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_columns()
