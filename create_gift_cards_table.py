import psycopg2
import os
from dotenv import load_dotenv

def get_db_connection():
    load_dotenv()
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'postgres'),
        password=os.environ.get('DB_PASSWORD', 'jv123'),
        database=os.environ.get('DB_NAME', 'jv_studio_pg_db'),
        port=os.environ.get('DB_PORT', '5432')
    )

def create_gift_cards_table():
    print("🚀 Iniciando migración de tabla 'gift_cards' (Direct Connect)...")
    conn = None
    try:
        conn = get_db_connection()
        conn.autocommit = False # Explicit transaction control
        
        # Windows Postgres encoding fix if needed
        try:
             conn.set_client_encoding('LATIN1')
        except:
             pass

        cursor = conn.cursor()
        
        # 1. Crear la tabla gift_cards
        print("🛠️  Creando tabla 'gift_cards'...")
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS gift_cards (
            id SERIAL PRIMARY KEY,
            code VARCHAR(50) NOT NULL UNIQUE,
            initial_amount DECIMAL(10, 2) NOT NULL CHECK (initial_amount >= 0),
            current_balance DECIMAL(10, 2) NOT NULL CHECK (current_balance >= 0),
            status VARCHAR(20) NOT NULL DEFAULT 'activa' CHECK (status IN ('activa', 'canjeada', 'vencida', 'anulada')),
            expiration_date DATE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            purchaser_name VARCHAR(255),
            recipient_name VARCHAR(255)
        );
        """
        cursor.execute(create_table_sql)
        
        # 2. Crear índices
        print("索引  Creando índices...")
        create_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_gift_cards_code ON gift_cards(code);
        """
        cursor.execute(create_index_sql)
        
        # Opcional: Indice parcial
        # Note: syntax might vary slightly but this is standard PG
        create_partial_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_gift_cards_active ON gift_cards(status) WHERE status = 'activa';
        """
        cursor.execute(create_partial_index_sql)

        conn.commit()
        print("✅ Tabla 'gift_cards' creada/verificada exitosamente.")

        # VERIFICATION IMMEDIATELY
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='gift_cards'")
        cols = cursor.fetchall()
        print(f"VERIFICATION: Found {len(cols)} columns in 'gift_cards'.")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Error durante la migración: {e}")
    finally:
        if conn:
            conn.close()
        print("🔒 Conexión cerrada.")

if __name__ == "__main__":
    create_gift_cards_table()
