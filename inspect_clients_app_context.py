
from app import create_app
from app.db import get_db
import sys
from dotenv import load_dotenv
import os

load_dotenv()

app = create_app()

with app.app_context():
    db = get_db()
    with open("client_columns.txt", "w", encoding="utf-8") as f:
        with db.cursor() as cursor:
            f.write("--- COLUMNS IN CLIENTES ---\n")
            cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'clientes' ORDER BY column_name;")
            for col in cursor.fetchall():
                f.write(f"{col[0]} ({col[1]})\n")
                
            f.write("\n--- CHECKING PERMISSIONS ---\n")
            try:
                 cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name='clientes' AND column_name='saldo_monedero'")
                 if not cursor.fetchone():
                     f.write("Adding saldo_monedero...\n")
                     cursor.execute("ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00;")
                     db.commit()
                     f.write("Added saldo_monedero successfully.\n")
                 else:
                     f.write("saldo_monedero already exists.\n")
            except Exception as e:
                f.write(f"Error modifying table: {e}\n")
