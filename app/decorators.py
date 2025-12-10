from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Intentamos obtener el rol de forma segura
        # Buscamos 'rol_nombre' (nuevo estándar) o 'rol' (viejo) por compatibilidad
        rol_actual = getattr(current_user, 'rol_nombre', None) or getattr(current_user, 'rol', None)
        
        # 2. Validamos
        if not current_user.is_authenticated or rol_actual != 'Administrador':
            flash('Acceso denegado. Se requieren permisos de Administrador.', 'danger')
            return redirect(url_for('main.index'))
        
        return f(*args, **kwargs)
    return decorated_function