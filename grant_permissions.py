import psycopg2

passwords = ["jv123", "postgres", "admin", "12345", "root", ""]

for pwd in passwords:
    try:
        conn = psycopg2.connect(
            host="localhost",
            user="postgres",
            password=pwd,
            database="jv_studio_pg_db",
            port=5432
        )
        print(f"Success with password: '{pwd}'")
        
        with conn.cursor() as cursor:
            cursor.execute("GRANT ALL ON SCHEMA public TO jv_user;")
            # Tambien asegurarse que jv_user sea dueño quizás
            # cursor.execute("ALTER SCHEMA public OWNER TO jv_user;")
            conn.commit()
            print("Permissions granted!")
            break
    except Exception as e:
        print(f"Failed with '{pwd}': {e}")
