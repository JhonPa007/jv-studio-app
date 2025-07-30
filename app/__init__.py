# app/__init__.py
import os
from flask import Flask
from flask_login import LoginManager

login_manager = LoginManager()

def create_app():
    """
    Función fábrica de la aplicación. Crea y configura la instancia de Flask.
    """
    app = Flask(__name__, instance_relative_config=True) # Habilitar la carpeta 'instance'

    # --- Configuración de la Aplicación ---
    # Lee la SECRET_KEY desde una variable de entorno.
    # El segundo valor es uno por defecto SOLO para desarrollo local.
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'una-clave-secreta-muy-dificil-de-adivinar'),
        
        # Leemos la configuración de la base de datos, con valores por defecto para desarrollo
        DB_HOST=os.environ.get('DB_HOST', 'localhost'),
        DB_USER=os.environ.get('DB_USER', 'tu_usuario_mysql'),
        DB_NAME=os.environ.get('DB_NAME', 'jv_studio_db')
        # La contraseña (DB_PASSWORD) se leerá de forma segura directamente en db.py
    )

    # --- Configuración de Flask-Login ---
    login_manager.login_view = 'main.login'
    login_manager.login_message = "Por favor, inicie sesión para acceder a esta página."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)
    
    # Importar y registrar el módulo de base de datos
    from . import db
    db.init_app(app)

    # --- Registrar Blueprints y Modelos ---
    from .routes import main_bp as main_blueprint
    app.register_blueprint(main_blueprint)

    from . import models
    
    return app