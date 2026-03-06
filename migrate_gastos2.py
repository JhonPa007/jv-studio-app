from app import create_app
from app.db import get_db

app = create_app()

def migrate():
    with app.app_context():
        db = get_db()
        try:
            with db.cursor() as cursor:
                cursor.execute("""
                    ALTER TABLE gastos 
                    ADD COLUMN IF NOT EXISTS estado_confirmacion VARCHAR(20) DEFAULT 'Pendiente'
                """)
                cursor.execute("""
                    UPDATE gastos 
                    SET estado_confirmacion = 'Confirmado'
                    WHERE estado_confirmacion = 'Pendiente'
                """)
                db.commit()
                print("Migration successful: Added estado_confirmacion to gastos.")
        except Exception as e:
            db.rollback()
            print("Migration failed:", e)

if __name__ == "__main__":
    migrate()
