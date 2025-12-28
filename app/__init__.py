import os
import psycopg2.extras
from flask import Flask, session
from flask_login import LoginManager, current_user
from config import Config

# Inicializamos el Login Manager
login_manager = LoginManager()

def create_app():
    """
    Función fábrica de la aplicación.
    """
    app = Flask(__name__, instance_relative_config=True)
    
    # Cargar configuración desde config.py
    app.config.from_object(Config)

    # Configurar Login
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    login_manager.login_message = "Por favor, inicie sesión para acceder a esta página."
    login_manager.login_message_category = "warning"

    # Inicializar Base de Datos
    from . import db
    db.init_app(app)

    # ----------------------------------------------------------
    # INYECTOR GLOBAL (Temas y Sucursales para todas las vistas)
    # ----------------------------------------------------------
    @app.context_processor
    def inject_global_data():
        # 1. Tema por Defecto
        tema = {
            'primario': '#ffc107', 'secundario': '#3a3a3a', 'fondo': '#212529', 'texto': '#ffffff',
            'sidebar_fondo': '#000000', 'sidebar_texto': '#ffffff', 'navbar_fondo': '#1a1a1a'
        }
        
        mis_sucursales = []
        sucursal_actual = None
        config_sistema = None 
        
        try:
            conn = db.get_db()
            if conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    
                    # A. Cargar Configuración Visual
                    try:
                        cursor.execute("SELECT * FROM configuracion_sistema WHERE id = 1")
                        config_db = cursor.fetchone()
                        
                        if config_db:
                            config_sistema = config_db
                            # Actualizar claves si existen en la BD
                            for key in tema.keys():
                                db_key = f"color_{key}" if key != 'primario' and key != 'secundario' and key != 'fondo' and key != 'texto' else f"color_{key}"
                                if config_db.get(db_key):
                                    tema[key] = config_db[db_key]
                            # Mapeo manual para los básicos si los nombres difieren
                            if config_db.get('color_primario'): tema['primario'] = config_db['color_primario']
                            if config_db.get('color_secundario'): tema['secundario'] = config_db['color_secundario']
                            if config_db.get('color_fondo'): tema['fondo'] = config_db['color_fondo']
                            if config_db.get('color_texto'): tema['texto'] = config_db['color_texto']
                    except Exception:
                        pass 

                    # B. Cargar Sucursales (Solo si hay usuario)
                    if current_user.is_authenticated:
                        try:
                            # Verificar si es admin (comprobando atributo rol_nombre o rol)
                            rol = getattr(current_user, 'rol_nombre', getattr(current_user, 'rol', ''))
                            
                            if rol == 'Administrador':
                                cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
                            else:
                                cursor.execute("""
                                    SELECT s.id, s.nombre
                                    FROM sucursales s
                                    JOIN empleado_sucursales es ON s.id = es.sucursal_id
                                    WHERE es.empleado_id = %s AND s.activo = TRUE
                                    ORDER BY s.nombre
                                """, (current_user.id,))
                            
                            mis_sucursales = cursor.fetchall()
                        except Exception:
                            pass

                    # C. Cargar Datos de la Sucursal Actual (Para el Footer)
                    sucursal_id = session.get('sucursal_id')
                    config_sucursal = None # Variable para config especifica de sucursal
                    
                    if sucursal_id:
                        try:
                            cursor.execute("SELECT * FROM sucursales WHERE id = %s", (sucursal_id,))
                            sucursal_actual = cursor.fetchone()
                            
                            # Cargar Configuración de Sucursal (Agenda, Fuentes, etc.)
                            cursor.execute("SELECT * FROM configuracion_sucursal WHERE sucursal_id = %s", (sucursal_id,))
                            config_sucursal = cursor.fetchone()
                            
                        except Exception:
                            pass

        except Exception as e:
            # Loguear error pero no romper la app
            app.logger.error(f"Error en inject_global_data: {e}")
        
        return dict(
            tema_sistema=tema, 
            mis_sucursales=mis_sucursales, 
            sucursal_actual=sucursal_actual,
            config_sistema=config_sistema,
            config_sucursal=config_sucursal 
        )
    # ----------------------------------------------------------

    # Registrar Rutas (Blueprint)
    from .routes import main_bp
    app.register_blueprint(main_bp)

    # Importar modelos para que Flask-Login los reconozca
    from . import models

    from . import routes_finanzas
    app.register_blueprint(routes_finanzas.finanzas_bp)
    
    from .routes_inventario import inventario_bp
    app.register_blueprint(inventario_bp)
    
    return app

    

