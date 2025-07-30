# app/decorators.py
from functools import wraps
from flask import abort
from flask_login import current_user

def admin_required(f):
    """
    Decorador que asegura que el usuario actual haya iniciado sesión Y tenga el rol de 'Administrador'.
    Si no cumple, devuelve un error 403 (Forbidden).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'Administrador':
            abort(403) # El usuario no tiene permiso
        return f(*args, **kwargs)
    return decorated_function