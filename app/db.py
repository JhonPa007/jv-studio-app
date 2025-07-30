import mysql.connector
import os # <-- Añadir esta importación
from flask import g, current_app

def get_db():
    if 'db' not in g:
        # Ahora lee los datos desde la configuración de la app
        g.db = mysql.connector.connect(
            host=current_app.config['DB_HOST'],
            user=current_app.config['DB_USER'],
            password=os.environ.get('DB_PASSWORD'), # <-- Lee la contraseña desde una variable de entorno
            database=current_app.config['DB_NAME']
        )
    return g.db

def close_db(e=None):
    """
    Cierra la conexión a la base de datos al final de la petición.
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_app(app):
    """
    Registra el comando para cerrar la base de datos con la aplicación Flask.
    """
    app.teardown_appcontext(close_db)