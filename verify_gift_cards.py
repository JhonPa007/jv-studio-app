import psycopg2
from app.db import get_db
from flask import Flask

app = Flask(__name__)
# Fake secret key for context
app.config['SECRET_KEY'] = 'dev'

def verify_table():
    print("🔍 Verificando creación de tabla 'gift_cards'...")
    with app.app_context():
        from dotenv import load_dotenv
        load_dotenv()
        
        db = get_db()
        if not db:
            print("❌ No hay conexión a BD.")
            return

        try:
            with db.cursor() as cursor:
                # Consultar information_schema
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'gift_cards';
                """)
                columns = cursor.fetchall()
                
                if not columns:
                    print("❌ La tabla 'gift_cards' NO existe.")
                else:
                    print(f"✅ La tabla 'gift_cards' existe con {len(columns)} columnas:")
                    for col in columns:
                        print(f"   - {col[0]} ({col[1]})")

                # Verificar índices
                cursor.execute("""
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE tablename = 'gift_cards';
                """)
                indexes = cursor.fetchall()
                print(f"✅ Índices encontrados: {len(indexes)}")
                for idx in indexes:
                    print(f"   - {idx[0]}")

        except Exception as e:
            print(f"❌ Error verificando: {e}")

if __name__ == "__main__":
    verify_table()
