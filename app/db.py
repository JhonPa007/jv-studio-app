import os
import psycopg2
import psycopg2.extras
from flask import g, current_app

def get_db():
    if 'db' not in g:
        # 1. Intentamos leer la URL de la base de datos desde las variables de entorno (Nube)
        database_url = os.environ.get('DATABASE_URL')
        
        try:
            if database_url:
                # MODO NUBE (Railway)
                g.db = psycopg2.connect(database_url)
                print("✅ Conectado a base de datos NUBE")
            else:
                # MODO LOCAL (Tu PC)
                print("⚠️ Variable DATABASE_URL no encontrada, usando localhost...")
                g.db = psycopg2.connect(
                    host="localhost",
                    user="postgres",       
                    password="TU_CONTRASEÑA_LOCAL_AQUI",  # <--- Asegúrate de poner tu clave local si vas a probar en tu PC
                    database="jv_studio_db"
                )
                print("✅ Conectado a base de datos LOCAL")
        except Exception as e:
            print(f"❌ Error crítico conectando a PostgreSQL: {e}")
            g.db = None # Importante para evitar el error 'NoneType' posterior
            
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_app(app):
    app.teardown_appcontext(close_db)