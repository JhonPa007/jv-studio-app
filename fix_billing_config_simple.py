
from app import create_app
from app.db import get_db
import psycopg2.extras

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("Checking configuration...")
        cursor.execute("SELECT * FROM configuracion_sistema WHERE id = 1")
        config = cursor.fetchone()
        
        if config:
            print("Configuration found:")
            print(config)
            if not config['ruc_empresa']:
                print("RUC is missing. 更新ing...")
                cursor.execute("""
                    UPDATE configuracion_sistema 
                    SET ruc_empresa = %s 
                    WHERE id = 1
                """, ('20614287561',))
                db.commit()
                print("RUC updated.")
            else:
                print(f"RUC already exists: {config['ruc_empresa']}")
        else:
            print("Configuration NOT found (id=1). Creating default record...")
            sql_insert = """
                INSERT INTO configuracion_sistema (id, ruc_empresa, razon_social, direccion_fiscal, ubigeo, clave_certificado, usuario_sol, clave_sol)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql_insert, ('20614287561', '', '', '', '', '', ''))
            db.commit()
            print("Default configuration created with RUC 20614287561.")

    db.close()
