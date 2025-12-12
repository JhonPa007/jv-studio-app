import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'miclave_super_secreta_jvstudio_2025'
    
    # --- LÓGICA DE CONEXIÓN A BASE DE DATOS ---
    # 1. Primero intentamos leer la URL completa (Así funciona Railway)
    database_url = os.environ.get('DATABASE_URL')

    if database_url:
        # CORRECCIÓN PARA POSTGRESQL EN ALGUNAS LIBRERÍAS
        # A veces la URL empieza con "postgres://" y SQLAlchemy necesita "postgresql://"
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        SQLALCHEMY_DATABASE_URI = database_url
        print("✅ Configuración: Usando Base de Datos NUBE (DATABASE_URL)")
    
    else:
        # 2. Si no hay URL completa, usamos la configuración por partes (Tu PC Local)
        DB_HOST = os.environ.get('DB_HOST') or 'localhost'
        DB_USER = os.environ.get('DB_USER') or 'postgres'
        DB_PASSWORD = os.environ.get('DB_PASSWORD') or 'jv123' # Pon tu clave local si la necesitas
        DB_NAME = os.environ.get('DB_NAME') or 'jv_studio_pg_db' # Asegúrate que coincida con tu BD local
        DB_PORT = os.environ.get('DB_PORT') or '5432'

        SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        print("🏠 Configuración: Usando Base de Datos LOCAL")

    SQLALCHEMY_TRACK_MODIFICATIONS = False