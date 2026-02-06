import psycopg2
import os
from dotenv import load_dotenv

def verify_to_file():
    load_dotenv()
    try:
        conn = psycopg2.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'postgres'),
            password=os.environ.get('DB_PASSWORD', 'jv123'),
            database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
            port=os.environ.get('DB_PORT', '5432')
        )
        conn.set_client_encoding('LATIN1')
        cursor = conn.cursor()
        
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='gift_cards'")
        cols = cursor.fetchall()
        
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename='gift_cards'")
        indexes = cursor.fetchall()

        with open('verification_result.txt', 'w') as f:
            if cols:
                f.write(f"SUCCESS: Found {len(cols)} columns.\n")
                for c in cols:
                    f.write(f" - {c[0]}\n")
                f.write(f"Indexes: {len(indexes)}\n")
                for i in indexes:
                    f.write(f" - {i[0]}\n")
            else:
                f.write("FAILURE: Table not found.\n")
                
        conn.close()
    except Exception as e:
        with open('verification_result.txt', 'w') as f:
            f.write(f"ERROR: {e}\n")

if __name__ == "__main__":
    verify_to_file()
