from flask_login import UserMixin
from . import login_manager
from .db import get_db
import psycopg2.extras

class User(UserMixin):
    # Actualizamos el constructor para aceptar 'sucursal_id'
    def __init__(self, id, nombres, apellidos, email, rol_id, rol_nombre, sucursal_id=None):
        self.id = id
        self.nombres = nombres
        self.apellidos = apellidos
        self.email = email
        self.rol_id = rol_id
        self.rol_nombre = rol_nombre
        self.sucursal_id = sucursal_id # <--- ESTO FALTABA
        self._permisos = None 

    def get_full_name(self):
        return f"{self.nombres} {self.apellidos}"

    @property
    def permisos(self):
        if self._permisos is None:
            if self.rol_id is None:
                self._permisos = set()
            else:
                db = get_db()
                try:
                    # Usamos RealDictCursor para consistencia
                    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                        sql = """
                            SELECT p.nombre 
                            FROM permisos p
                            JOIN rol_permisos rp ON p.id = rp.permiso_id
                            WHERE rp.rol_id = %s
                        """
                        cursor.execute(sql, (self.rol_id,))
                        # Extraemos solo los nombres de los permisos
                        self._permisos = {row['nombre'] for row in cursor.fetchall()}
                except Exception:
                    self._permisos = set()
                    
        return self._permisos

    def can(self, permiso):
        return 'acceso_total' in self.permisos or permiso in self.permisos
    
    def is_admin(self):
        return self.can('acceso_total')

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # JOIN para obtener el nombre del rol en cada carga de página
            sql = """
                SELECT e.*, r.nombre as rol_nombre
                FROM empleados e
                LEFT JOIN roles r ON e.rol_id = r.id
                WHERE e.id = %s
            """
            cursor.execute(sql, (user_id,))
            user_data = cursor.fetchone()
            
            if user_data:
                # Aquí también pasamos sucursal_id
                return User(
                    id=user_data['id'], 
                    nombres=user_data['nombres'],
                    apellidos=user_data['apellidos'],
                    email=user_data['email'],
                    rol_id=user_data['rol_id'],
                    rol_nombre=user_data['rol_nombre'],
                    sucursal_id=user_data['sucursal_id'] # <--- IMPORTANTE
                )
    except Exception as e:
        print(f"Error cargando usuario: {e}")
        return None
    return None