
import os
import psycopg2
from flask import g
from app import create_app
from app.db import get_db

app = create_app()

def apply_columns():
    with app.app_context():
        # Force production usage if env var not set (optional fallback or logging)
        print("Iniciando migración de columnas en contexto Flask...")
        
        conn = get_db()
        if not conn:
            print("❌ No se pudo conectar a la base de datos (get_db retornó None).")
            return

        try:
            cur = conn.cursor()
            
            # Columnas a agregar
            # Verificar si existen antes o usar exception handling
            columns = [
                ("agenda_hora_inicio", "TIME DEFAULT '08:00:00'"),
                ("agenda_hora_fin", "TIME DEFAULT '22:00:00'")
            ]

            for col_name, col_def in columns:
                try:
                    print(f"Intentando agregar {col_name}...")
                    cur.execute(f"ALTER TABLE configuracion_sucursal ADD COLUMN {col_name} {col_def};")
                    print(f"✅ Columna '{col_name}' agregada con éxito.")
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback() 
                    print(f"⚠️ La columna '{col_name}' ya existe. (Omitiendo)")
                except Exception as e:
                    conn.rollback()
                    print(f"❌ Error al agregar '{col_name}': {e}")
                else:
                    conn.commit()

            cur.close()
            # No cerramos conn aquí porque Flask lo maneja en teardown, 
            # pero commit es necesario.
            print("--- Proceso finalizado ---")

        except Exception as e:
            print(f"Error general en el script: {e}")

if __name__ == "__main__":
    apply_columns()
