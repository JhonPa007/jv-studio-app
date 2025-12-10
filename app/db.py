import psycopg2
import psycopg2.extras
from flask import g, current_app

def get_db():
    if 'db' not in g:
        try:
            # Conexión profesional leyendo de la configuración cargada (config.py -> .env)
            g.db = psycopg2.connect(
                host=current_app.config['DB_HOST'],
                user=current_app.config['DB_USER'],
                password=current_app.config['DB_PASSWORD'],
                dbname=current_app.config['DB_NAME'],
                port=current_app.config['DB_PORT']
            )
            g.db.autocommit = True
            
        except psycopg2.Error as e:
            print(f"Error crítico conectando a PostgreSQL: {e}")
            return None

    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_app(app):
    app.teardown_appcontext(close_db)