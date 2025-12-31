import os
from dotenv import load_dotenv

# Force load .env
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
    print("DOTENV cargado desde:", dotenv_path)
else:
    print("DOTENV no encontrado en:", dotenv_path)

from app import create_app
from app.db import get_db

def update_schema():
    app = create_app()
    with app.app_context():
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            print("Verificando tabla 'compras'...")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compras (
                    id SERIAL PRIMARY KEY,
                    proveedor_id INTEGER REFERENCES proveedores(id),
                    sucursal_id INTEGER REFERENCES sucursales(id),
                    fecha_compra DATE DEFAULT CURRENT_DATE,
                    tipo_comprobante VARCHAR(50),
                    serie_numero_comprobante VARCHAR(100),
                    subtotal DECIMAL(10, 2) DEFAULT 0.00,
                    impuestos DECIMAL(10, 2) DEFAULT 0.00,
                    total DECIMAL(10, 2) DEFAULT 0.00,
                    estado_pago VARCHAR(20) DEFAULT 'Pendiente',
                    notas TEXT,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            print("Verificando tabla 'compra_items'...")
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
            
            conn.commit()
            print("Tablas 'compras' y 'compra_items' creadas/verificadas correctamente.")
            
        except Exception as e:
            conn.rollback()
            print(f"Error actualizando esquema: {e}")
        finally:
            cursor.close()

if __name__ == "__main__":
    update_schema()
