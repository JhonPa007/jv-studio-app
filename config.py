import os
from dotenv import load_dotenv

load_dotenv() # Carga variables del archivo .env

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una-clave-secreta-muy-dificil-de-adivinar'
    MYSQL_HOST = os.environ.get('MYSQL_HOST') or 'localhost'
    MYSQL_USER = os.environ.get('MYSQL_USER') or 'tu_usuario_mysql'
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD') or 'tu_password_mysql'
    MYSQL_DB = os.environ.get('MYSQL_DB') or 'jv_studio_db'
    MYSQL_CURSORCLASS = 'DictCursor' # Devuelve filas como diccionarios

    # Si usas SQLAlchemy:
    # SQLALCHEMY_DATABASE_URI = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}/{MYSQL_DB}"
    # SQLALCHEMY_TRACK_MODIFICATIONS = False