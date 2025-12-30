
import psycopg2
from app.db import get_db_connection

def add_agenda_times_columns():
    conn = get_db_connection()
    if not conn:
        print("No se pudo conectar a la BD.")
        return

    try:
        cur = conn.cursor()
        
        # Agregar columnas si no existen
        columns = [
            ("agenda_hora_inicio", "TIME DEFAULT '08:00:00'"),
            ("agenda_hora_fin", "TIME DEFAULT '22:00:00'")
        ]

        for col_name, col_def in columns:
            try:
                cur.execute(f"ALTER TABLE configuracion_sucursal ADD COLUMN {col_name} {col_def};")
                print(f"Columna '{col_name}' agregada con éxito.")
            except psycopg2.errors.DuplicateColumn:
                conn.rollback() # Necesario hacer rollback si falla una transacción
                print(f"La columna '{col_name}' ya existe.")
            except Exception as e:
                conn.rollback()
                print(f"Error al agregar '{col_name}': {e}")
            else:
                conn.commit()

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error general: {e}")
        if conn:
            conn.close()

if __name__ == "__main__":
    add_agenda_times_columns()
