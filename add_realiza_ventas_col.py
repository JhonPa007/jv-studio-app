
import psycopg2
import os

def add_column():
    try:
        # Direct connection based on app/db.py
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            conn = psycopg2.connect(database_url)
        else:
            conn = psycopg2.connect(
                host="localhost",
                user="postgres",       
                password="jv123",
                database="jv_studio_pg_db"
            )
            
        cur = conn.cursor()
        
        # Check if column exists
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='empleados' AND column_name='realiza_ventas'")
        if cur.fetchone():
            print("Column 'realiza_ventas' already exists.")
        else:
            print("Adding column 'realiza_ventas'...")
            cur.execute("ALTER TABLE empleados ADD COLUMN realiza_ventas BOOLEAN DEFAULT TRUE")
            conn.commit()
            print("Column added successfully.")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    add_column()
