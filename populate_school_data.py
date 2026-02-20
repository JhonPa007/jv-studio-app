import psycopg2
from app.db import get_db
from app import create_app

app = create_app()

def populate_data():
    with app.app_context():
        try:
            db = get_db()
            with db.cursor() as cursor:
                # 1. Insert Course if not exists
                print("Checking/Inserting Course...")
                cursor.execute("SELECT id FROM escuela_cursos WHERE nombre = 'Barbería Profesional'")
                curso = cursor.fetchone()
                
                if not curso:
                    cursor.execute("""
                        INSERT INTO escuela_cursos (nombre, costo_matricula, costo_mensualidad, duracion_meses, activo)
                        VALUES ('Barbería Profesional', 150.00, 350.00, 3, TRUE)
                        RETURNING id
                    """)
                    curso_id = cursor.fetchone()[0]
                    print(f"Course created with ID: {curso_id}")
                else:
                    curso_id = curso[0]
                    print(f"Course already exists with ID: {curso_id}")
                
                # 2. Insert Group if not exists
                print("Checking/Inserting Group...")
                cursor.execute("SELECT id FROM escuela_grupos WHERE codigo_grupo = 'G-2026-FEB-M'")
                grupo = cursor.fetchone()
                
                if not grupo:
                    cursor.execute("""
                        INSERT INTO escuela_grupos (codigo_grupo, curso_id, fecha_inicio, dias_clase, hora_inicio, hora_fin, activo)
                        VALUES ('G-2026-FEB-M', %s, '2026-02-23', 'Lunes, Miércoles, Viernes', '09:00', '12:00', TRUE)
                        RETURNING id
                    """, (curso_id,))
                    grupo_id = cursor.fetchone()[0]
                    print(f"Group created with ID: {grupo_id}")
                else:
                    print("Group already exists.")

                db.commit()
                print("Data population completed!")

        except Exception as e:
            print(f"Error populating data: {e}")

if __name__ == "__main__":
    populate_data()
