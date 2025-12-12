import os
import psycopg2
import psycopg2.extras
from flask import g, current_app

def get_db():
    if 'db' not in g:
        # 1. Intentamos leer la dirección de la nube
        database_url = os.environ.get('DATABASE_URL')
        
        if database_url:
            # CONEXIÓN MODO NUBE (Railway)
            g.db = psycopg2.connect(database_url)
        else:
            # CONEXIÓN MODO LOCAL (Tu PC)
            g.db = psycopg2.connect(
                host="localhost",
                user="postgres",       # Tus datos locales
                password="jv123", 
                database="jv_studio_db"
            )
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_app(app):
    app.teardown_appcontext(close_db)