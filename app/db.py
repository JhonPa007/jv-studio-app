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
                    password="jv123",  # <--- Asegúrate de poner tu clave local si vas a probar en tu PC
                    database="jv_studio_pg_db"
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

def check_schema_updates(app):
    """
    Función de auto-migración simple para asegurar que las columnas existan en Producción.
    Se debe llamar al iniciar la app.
    """
    with app.app_context():
        db = get_db()
        if not db:
            return
            
        try:
            with db.cursor() as cursor:
                # ---------------------------------------------------------
                # 0. CREACIÓN DE TABLAS FALTANTES (Auto-Fix)
                # ---------------------------------------------------------
                # Tabla Compras
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS compras (
                        id SERIAL PRIMARY KEY,
                        proveedor_id INTEGER REFERENCES proveedores(id),
                        sucursal_id INTEGER REFERENCES sucursales(id),
                        fecha_compra DATE DEFAULT CURRENT_DATE,
                        tipo_comprobante VARCHAR(50),
                        serie_numero_comprobante VARCHAR(100),
                        monto_subtotal DECIMAL(10, 2) DEFAULT 0.00,
                        monto_impuestos DECIMAL(10, 2) DEFAULT 0.00,
                        monto_total DECIMAL(10, 2) DEFAULT 0.00,
                        estado_pago VARCHAR(20) DEFAULT 'Pendiente',
                        notas TEXT,
                        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # Tabla Detalle Compras
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS compra_items (
                        id SERIAL PRIMARY KEY,
                        compra_id INTEGER REFERENCES compras(id) ON DELETE CASCADE,
                        producto_id INTEGER REFERENCES productos(id),
                        cantidad INTEGER NOT NULL,
                        costo_unitario DECIMAL(10, 2) NOT NULL,
                        subtotal DECIMAL(10, 2) NOT NULL
                    );
                """)
                
                # Tabla Kardex (Movimientos de Inventario)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS kardex (
                        id SERIAL PRIMARY KEY,
                        producto_id INTEGER REFERENCES productos(id),
                        tipo_movimiento VARCHAR(50), 
                        cantidad INTEGER,
                        stock_anterior INTEGER,
                        stock_actual INTEGER,
                        motivo TEXT,
                        usuario_id INTEGER REFERENCES empleados(id),
                        venta_id INTEGER REFERENCES ventas(id),
                        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # Tabla Comisiones (Generales)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS comisiones (
                        id SERIAL PRIMARY KEY,
                        venta_item_id INTEGER REFERENCES venta_items(id) ON DELETE CASCADE,
                        empleado_id INTEGER REFERENCES empleados(id),
                        monto_comision DECIMAL(10, 2) NOT NULL,
                        porcentaje DECIMAL(5, 2) DEFAULT 0.00,
                        fecha_generacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        estado VARCHAR(20) DEFAULT 'Pendiente',
                        pago_caja_sesion_id INTEGER, 
                        fecha_pago TIMESTAMP
                    );
                """)

                # Tabla Loyalty Rules
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS loyalty_rules (
                        id SERIAL PRIMARY KEY,
                        nombre VARCHAR(100) NOT NULL,
                        servicio_id INTEGER REFERENCES servicios(id),
                        cantidad_requerida INTEGER NOT NULL,
                        periodo_meses INTEGER NOT NULL,
                        descuento_porcentaje NUMERIC(5, 2) NOT NULL,
                        activo BOOLEAN DEFAULT TRUE
                    );
                """)
                
                # Tabla CRM Config
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS crm_config (
                        id SERIAL PRIMARY KEY,
                        tipo_evento VARCHAR(50) NOT NULL,
                        mensaje_plantilla TEXT,
                        dias_anticipacion INTEGER DEFAULT 0,
                        activo BOOLEAN DEFAULT TRUE
                    );
                """)

                db.commit()

                # Lista de Columnas Nuevas a Verificar/Agregar
                columns_to_check = [
                    # tabla, columna, definición
                    ("configuracion_sucursal", "agenda_hora_inicio", "TIME DEFAULT '08:00:00'"),
                    ("configuracion_sucursal", "agenda_hora_fin", "TIME DEFAULT '22:00:00'"),
                    # Agregamos las de empleados también por seguridad
                    ("empleados", "tipo_contrato", "VARCHAR(20) DEFAULT 'FIJO'"),
                    ("empleados", "puede_realizar_servicios", "BOOLEAN DEFAULT TRUE"),
                    ("empleados", "porcentaje_comision_productos", "DECIMAL(5,2) DEFAULT 0.00"),
                    ("empleados", "configuracion_comision", "JSONB DEFAULT '{}'"),
                    # VENTAS
                    ("venta_items", "es_hora_extra", "BOOLEAN DEFAULT FALSE"),
                    ("venta_items", "porcentaje_servicio_extra", "DECIMAL(5,2) DEFAULT 0.00"),
                    ("venta_items", "comision_servicio_extra", "DECIMAL(10,2) DEFAULT 0.00"),
                    ("venta_items", "entregado_al_colaborador", "BOOLEAN DEFAULT FALSE"),
                    # PRODUCTOS
                    ("productos", "comision_vendedor_monto", "DECIMAL(10,2) DEFAULT 0.00"),
                    # COMISIONES (Fix para tablas antiguas)
                    ("comisiones", "porcentaje", "DECIMAL(5, 2) DEFAULT 0.00"),
                ]
                
                print("--- Iniciando Verificación de Schema (Auto-Migration) ---")
                for table, col, definition in columns_to_check:
                    try:
                        # Intentar agregar columna. Si falla porque existe, ignoramos.
                        # Postgres no tiene "ADD COLUMN IF NOT EXISTS" nativo en versiones viejas,
                        # pero el try/except es robusto.
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                        print(f"✅ Columna Agregada: {table}.{col}")
                    except psycopg2.errors.DuplicateColumn:
                        db.rollback() # Importante rollbackear el error
                        # print(f"ℹ️ Columna ya existe: {table}.{col}")
                    except psycopg2.errors.UndefinedTable:
                         db.rollback()
                         print(f"⚠️ Tabla no encontrada: {table}")
                    except Exception as e:
                        db.rollback()
                        print(f"❌ Error migrando {table}.{col}: {e}")
                    else:
                        db.commit()
                print("--- Verificación de Schema Finalizada ---")
                
        except Exception as e:
            print(f"Error general en check_schema_updates: {e}")
