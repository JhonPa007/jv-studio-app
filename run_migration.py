
from app import create_app
from app.db import get_db

def run_migration():
    app = create_app()
    with app.app_context():
        try:
            db = get_db()
            cur = db.cursor()
            
            print("Checking/Creating loyalty_rules table...")
            cur.execute("""
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
            
            print("Checking/Creating crm_config table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS crm_config (
                    id SERIAL PRIMARY KEY,
                    tipo_evento VARCHAR(50) NOT NULL,
                    mensaje_plantilla TEXT,
                    dias_anticipacion INTEGER DEFAULT 0,
                    activo BOOLEAN DEFAULT TRUE
                );
            """)
            
            db.commit()
            print("Migration completed successfully.")
            
        except Exception as e:
            print(f"Original Error: {repr(e)}")
            print(f"DB Object Type: {type(db)}")
            if hasattr(db, 'rollback'):
                db.rollback()
            else:
                print("DB object has no rollback method.")

if __name__ == "__main__":
    run_migration()
