import psycopg2
import sys

def last_check():
    try:
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",
            password="jv123",
            database="jv_studio_pg_db",
            port="5432"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='gift_cards'")
        count = cursor.fetchone()[0]
        
        with open('final_status.txt', 'w', encoding='utf-8') as f:
            if count > 0:
                f.write(f"EXISTS:{count}")
            else:
                f.write("NOT_FOUND")
    except Exception as e:
        with open('final_status.txt', 'w', encoding='utf-8') as f:
             f.write(f"ERROR:{str(e)}")

if __name__ == "__main__":
    last_check()
