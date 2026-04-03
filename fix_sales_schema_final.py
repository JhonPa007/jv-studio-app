import psycopg2
from app import create_app
from app.db import get_db

def migrate_missing_columns():
    app = create_app()
    with app.app_context():
        conn = get_db()
        conn.autocommit = True
        cur = conn.cursor()
        
        print("Starting comprehensive schema fix...")
        
        # 1. Clientes
        try:
            cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS saldo_monedero DECIMAL(10,2) DEFAULT 0.00")
            print("- Clientes: saldo_monedero added/checked.")
        except Exception as e: print(f"Error in clientes: {e}")

        # 2. Venta Items
        try:
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS porcentaje_servicio_extra DECIMAL(5,2) DEFAULT 0.00")
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS comision_servicio_extra DECIMAL(10,2) DEFAULT 0.00")
            cur.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS entregado_al_colaborador BOOLEAN DEFAULT FALSE")
            print("- Venta Items: extra columns added/checked.")
        except Exception as e: print(f"Error in venta_items: {e}")

        # 3. Comisiones
        try:
            cur.execute("ALTER TABLE comisiones ADD COLUMN IF NOT EXISTS porcentaje DECIMAL(5,2) DEFAULT 0.00")
            print("- Comisiones: porcentaje column added/checked.")
        except Exception as e: print(f"Error in comisiones: {e}")
        
        # 4. Check "Clientes Varios" presence
        cur.execute("SELECT id FROM clientes WHERE razon_social_nombres = 'Clientes Varios' LIMIT 1")
        if not cur.fetchone():
            print("- Clientes Varios not found. Adding it...")
            cur.execute("INSERT INTO clientes (razon_social_nombres, tipo_documento, numero_documento, direccion) VALUES ('Clientes Varios', 'DNI', '00000000', '-')")
            print("- Clientes Varios created.")

        print("Migration done successfully.")

if __name__ == "__main__":
    migrate_missing_columns()
