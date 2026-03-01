from app import create_app
from app.db import check_schema_updates

app = create_app()
with app.app_context():
    print("Aplicando actualizaciones de esquema...")
    check_schema_updates(app)
    print("¡Tablas creadas exitosamente!")
