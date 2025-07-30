# app/models.py
from flask_login import UserMixin
from . import login_manager
from .db import get_db

class User(UserMixin):
    def __init__(self, id, nombres, apellidos, email, rol_id, rol_nombre, sucursal_id):
        self.id = id
        self.nombres = nombres
        self.apellidos = apellidos
        self.email = email
        self.rol_id = rol_id
        self.rol = rol_nombre # Guardamos el nombre del rol para facilidad de uso
        self.sucursal_id = sucursal_id
        self._permisos = None # Caché para los permisos del usuario

    def get_full_name(self):
        """
        NUEVA FUNCIÓN: Devuelve el nombre completo del usuario.
        """
        return f"{self.nombres} {self.apellidos}"

    @property
    def permisos(self):
        """
        Obtiene y guarda en caché la lista de nombres de permisos para el rol del usuario.
        """
        if self._permisos is None:
            if self.rol_id is None:
                self._permisos = set() # Un usuario sin rol no tiene permisos
            else:
                db = get_db()
                with db.cursor() as cursor:
                    sql = """
                        SELECT p.nombre 
                        FROM permisos p
                        JOIN rol_permisos rp ON p.id = rp.permiso_id
                        WHERE rp.rol_id = %s
                    """
                    cursor.execute(sql, (self.rol_id,))
                    # Creamos un 'set' (conjunto) para búsquedas de permisos muy rápidas
                    self._permisos = {row[0] for row in cursor.fetchall()}
        return self._permisos

    def can(self, permiso):
        """
        Verifica si el usuario tiene un permiso específico.
        Permite que el rol 'Administrador' siempre tenga acceso a todo.
        """
        # El rol 'Administrador' (asumiendo que es el que tiene el permiso 'acceso_total') puede hacer todo
        return 'acceso_total' in self.permisos or permiso in self.permisos
    
    def is_admin(self):
        """ Conveniencia para chequear si es admin en las plantillas """
        return self.can('acceso_total')

# Esta función le dice a Flask-Login cómo cargar un usuario desde la base de datos
@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    with db.cursor(dictionary=True) as cursor:
        # Consulta actualizada con JOIN para obtener el nombre del rol
        sql = """
            SELECT e.*, r.nombre as rol_nombre
            FROM empleados e
            LEFT JOIN roles r ON e.rol_id = r.id
            WHERE e.id = %s
        """
        cursor.execute(sql, (user_id,))
        user_data = cursor.fetchone()
        
        if user_data:
            return User(
                id=user_data['id'], 
                nombres=user_data['nombres'],
                apellidos=user_data['apellidos'],
                email=user_data['email'],
                rol_id=user_data['rol_id'],
                rol_nombre=user_data['rol_nombre'],
                sucursal_id=user_data['sucursal_id']
            )
    return None