
from collections import OrderedDict
from flask import Blueprint, render_template, current_app, g, request, redirect, url_for, flash
from flask import jsonify, request, current_app, g 
from flask import flash, redirect, url_for, request, current_app, render_template
from datetime import date, datetime, time, timedelta # Asegúrate de tener 'date' y 'time'
import json
import math
#from . import main_bp
#from .db import get_db
import mysql.connector
import calendar
from werkzeug.security import generate_password_hash
from flask_login import login_user, logout_user, login_required, current_user
from .decorators import admin_required
from werkzeug.security import check_password_hash
from .db import get_db
from .models import User # Importamos nuestra clase User desde models.py
import pandas as pd
import io
from flask import Response
from urllib.parse import quote_plus
import pandas as pd
from werkzeug.utils import secure_filename
import os
from lxml import etree as ET
from flask import Response
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
import zipfile
import base64

from zeep import Client, Transport
from zeep.exceptions import Fault
from zeep.wsse.username import UsernameToken 
from datetime import datetime, timedelta, date, time, timezone


# --- Definición del Blueprint ---
# main_bp es el nombre que usamos para registrar las rutas en app/__init__.py
# y como prefijo en url_for (ej. 'main.listar_clientes')
main_bp = Blueprint('main', __name__)

# --- Funciones Auxiliares para la Base de Datos ---
def get_db():
    """
    Conecta a la base de datos. Si ya existe una conexión en el contexto
    de la aplicación (g), la reutiliza.
    """
    if 'db' not in g:
        g.db = mysql.connector.connect(
            host=current_app.config['MYSQL_HOST'],
            user=current_app.config['MYSQL_USER'],
            password=current_app.config['MYSQL_PASSWORD'],
            database=current_app.config['MYSQL_DB']
            # El cursor con dictionary=True se especifica al crear el cursor
        )
    return g.db


def timedelta_to_hhmm_str(td):
    """Convierte un timedelta a un string en formato HH:MM:SS."""
    if td is None: 
        return "00:00:00"
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def timedelta_to_time_obj(td): # Renombrada para claridad
    if td is None: return None
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return time(hours, minutes)

@main_bp.teardown_app_request
def teardown_db(exception):
    """
    Cierra la conexión a la base de datos al finalizar la petición.
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()


@main_bp.route('/')
@login_required
def index():
    """
    Muestra el dashboard principal con KPIs y alertas de cumpleaños.
    """
    db_conn = get_db()
    hoy = date.today()
    
    # Datos que se cargarán para todos los roles
    datos_para_plantilla = {}

    try:
        # Lógica para Administradores
        if current_user.rol == 'Administrador':
            with db_conn.cursor(dictionary=True) as cursor:
                # 1. Ventas del día
                cursor.execute("""
                    SELECT 
                        COUNT(id) as numero_ventas,
                        SUM(subtotal_servicios) as total_servicios,
                        SUM(subtotal_productos) as total_productos
                    FROM ventas 
                    WHERE DATE(fecha_venta) = %s AND estado_pago != 'Anulado'
                """, (hoy,))
                ventas_hoy = cursor.fetchone()

                # 2. Citas del día
                cursor.execute("SELECT COUNT(id) as numero_citas FROM reservas WHERE DATE(fecha_hora_inicio) = %s AND estado NOT IN ('Cancelada', 'No Asistio')", (hoy,))
                datos_para_plantilla['citas_hoy'] = cursor.fetchone()

                
                # 3. Productos con stock bajo
                cursor.execute("SELECT id, nombre, stock_actual, stock_minimo FROM productos WHERE activo = TRUE AND stock_actual <= stock_minimo ORDER BY stock_actual ASC")
                datos_para_plantilla['productos_stock_bajo'] = cursor.fetchall()
                
                # 4. NUEVA CONSULTA: MEMBRESÍAS POR VENCER ---
                fecha_limite_vencimiento = hoy + timedelta(days=7)
                sql_membresias = """
                    SELECT c.razon_social_nombres, c.apellidos, c.telefono, cm.fecha_fin, mp.nombre as plan_nombre
                    FROM cliente_membresias cm
                    JOIN clientes c ON cm.cliente_id = c.id
                    JOIN membresia_planes mp ON cm.plan_id = mp.id
                    WHERE cm.estado = 'Activa' AND cm.fecha_fin BETWEEN %s AND %s
                    ORDER BY cm.fecha_fin ASC
                """
                # --- CORRECCIÓN AQUÍ: Se eliminaron los .date() ---
                cursor.execute(sql_membresias, (hoy, fecha_limite_vencimiento))
                datos_para_plantilla['membresias_por_vencer'] = cursor.fetchall()
                              
        # Lógica para Colaboradores (No-Administradores)
        else:
            with db_conn.cursor(dictionary=True) as cursor:
                sql = """
                    SELECT r.id, r.fecha_hora_inicio, s.nombre as servicio_nombre,
                           CONCAT(c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) AS cliente_nombre
                    FROM reservas r JOIN servicios s ON r.servicio_id = s.id LEFT JOIN clientes c ON r.cliente_id = c.id
                    WHERE r.empleado_id = %s AND DATE(r.fecha_hora_inicio) = %s AND r.estado = 'Programada' AND r.fecha_hora_inicio >= NOW()
                    ORDER BY r.fecha_hora_inicio ASC LIMIT 5
                """
                cursor.execute(sql, (current_user.id, hoy))
                datos_para_plantilla['proximas_citas'] = cursor.fetchall()

        # --- LÓGICA DE CUMPLEAÑOS (se ejecuta para todos) ---
        anio_actual = hoy.year
        fecha_proxima = hoy + timedelta(days=2)
        with db_conn.cursor(dictionary=True) as cursor:
            # Cumpleaños de HOY
            sql_hoy = "SELECT c.id, c.razon_social_nombres, c.apellidos, c.telefono FROM clientes c LEFT JOIN cliente_comunicaciones cc ON c.id = cc.cliente_id AND cc.tipo_comunicacion = 'SALUDO_CUMPLEANOS' AND cc.año_aplicable = %s WHERE MONTH(c.fecha_nacimiento) = %s AND DAY(c.fecha_nacimiento) = %s AND cc.id IS NULL"
            cursor.execute(sql_hoy, (anio_actual, hoy.month, hoy.day))
            datos_para_plantilla['clientes_cumpleanos_hoy'] = cursor.fetchall()
            
            # Próximos cumpleaños
            sql_proximos = "SELECT c.id, c.razon_social_nombres, c.apellidos, c.telefono FROM clientes c LEFT JOIN cliente_comunicaciones cc ON c.id = cc.cliente_id AND cc.tipo_comunicacion = 'INVITACION_CUMPLEANOS' AND cc.año_aplicable = %s WHERE MONTH(c.fecha_nacimiento) = %s AND DAY(c.fecha_nacimiento) = %s AND cc.id IS NULL"
            cursor.execute(sql_proximos, (anio_actual, fecha_proxima.month, fecha_proxima.day))
            datos_para_plantilla['clientes_cumpleanos_proximos'] = cursor.fetchall()
            
        datos_para_plantilla['fecha_alerta_hoy'] = hoy
        datos_para_plantilla['fecha_alerta_proxima'] = fecha_proxima

    except mysql.connector.Error as err:
        flash(f"Error al cargar los datos del dashboard: {err}", "danger")

    return render_template('index.html', ventas_hoy=ventas_hoy, **datos_para_plantilla)

    

# --- RUTAS DE AUTENTICACIÓN ---

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Maneja el inicio de sesión de los usuarios (colaboradores).
    Versión actualizada para usar el nuevo sistema de roles.
    """
    # Si el usuario ya está logueado, lo redirigimos al dashboard
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = 'remember' in request.form

        if not email or not password:
            flash('Se requiere email y contraseña.', 'warning')
            return redirect(url_for('main.login'))

        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            # Consulta actualizada con JOIN para obtener el nombre del rol desde la tabla 'roles'
            sql = """
                SELECT e.*, r.nombre as rol_nombre
                FROM empleados e
                LEFT JOIN roles r ON e.rol_id = r.id
                WHERE e.email = %s AND e.activo = TRUE
            """
            cursor.execute(sql, (email,))
            user_from_db = cursor.fetchone()

            # Verificar si el usuario existe Y si la contraseña es correcta
            if not user_from_db or not user_from_db.get('password') or not check_password_hash(user_from_db['password'], password):
                flash('Email o contraseña incorrectos. Por favor, verifique sus credenciales.', 'danger')
                return redirect(url_for('main.login'))
            
            # Si las credenciales son válidas, crear el objeto User y loguear al usuario
            user_obj = User(
                id=user_from_db['id'], 
                nombres=user_from_db['nombres'],
                apellidos=user_from_db['apellidos'],
                email=user_from_db['email'],
                rol_id=user_from_db['rol_id'],
                rol_nombre=user_from_db['rol_nombre'], # <-- Usamos 'rol_nombre' de la consulta
                sucursal_id=user_from_db['sucursal_id']
            )
            
            login_user(user_obj, remember=remember)
            
            # Redirigir a la página principal (dashboard) después del login
            return redirect(url_for('main.index'))

    # Si la petición es GET, simplemente mostrar el formulario de login
    return render_template('login.html')


@main_bp.route('/logout')
@login_required # Solo un usuario logueado puede acceder a esta ruta para desloguearse
def logout():
    """
    Maneja el cierre de sesión del usuario.
    """
    logout_user()
    flash('Has cerrado sesión exitosamente.', 'success')
    return redirect(url_for('main.login'))


@main_bp.route('/api/clientes/registrar_comunicacion', methods=['POST'])
@login_required
def api_registrar_comunicacion():
    """
    API para registrar que se ha enviado una comunicación (saludo/invitación) a un cliente.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No se recibieron datos."}), 400

    cliente_id = data.get('cliente_id')
    tipo_comunicacion = data.get('tipo_comunicacion')
    anio_aplicable = data.get('anio_aplicable')
    
    if not all([cliente_id, tipo_comunicacion, anio_aplicable]):
        return jsonify({"success": False, "message": "Faltan datos requeridos."}), 400

    try:
        db = get_db()
        with db.cursor() as cursor:
            # Usamos INSERT IGNORE para evitar un error si se hace clic dos veces rápidamente.
            # La constraint UNIQUE en la tabla ya previene duplicados.
            sql = """
                INSERT IGNORE INTO cliente_comunicaciones 
                    (cliente_id, tipo_comunicacion, año_aplicable, registrado_por_colaborador_id)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (cliente_id, tipo_comunicacion, anio_aplicable, current_user.id))
            db.commit()

        return jsonify({"success": True, "message": "Comunicación registrada exitosamente."})

    except mysql.connector.Error as err:
        db.rollback()
        current_app.logger.error(f"Error DB en api_registrar_comunicacion: {err}")
        return jsonify({"success": False, "message": f"Error de base de datos: {err}"}), 500


@main_bp.route('/clientes')
@login_required
@admin_required # O el permiso que hayas definido
def listar_clientes():
    """
    Muestra la lista de clientes (personas, no empresas), con filtros de búsqueda.
    """
    db = get_db()
    
    # Obtener el término de búsqueda de la URL (ej: /clientes?q=Juan)
    termino_busqueda = request.args.get('q', '').strip()
    
    try:
        with db.cursor(dictionary=True) as cursor:
            # La consulta base siempre filtra para excluir a los RUC
            sql = """
                SELECT id, razon_social_nombres, apellidos, telefono, numero_documento, tipo_documento, puntos_fidelidad 
                FROM clientes
                WHERE (tipo_documento IS NULL OR tipo_documento != 'RUC')
            """
            params = []
            
            # Si el usuario escribió algo en la barra de búsqueda, se añade el filtro a la consulta
            if termino_busqueda:
                sql += " AND (razon_social_nombres LIKE %s OR apellidos LIKE %s OR numero_documento LIKE %s)"
                # Los '%' son comodines para que busque coincidencias parciales
                params.extend([f"%{termino_busqueda}%", f"%{termino_busqueda}%", f"%{termino_busqueda}%"])

            sql += " ORDER BY razon_social_nombres, apellidos"
            
            cursor.execute(sql, tuple(params))
            clientes = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los clientes: {err}", "danger")
        clientes = []

    return render_template('clientes/lista_clientes.html', 
                           clientes=clientes, 
                           termino_busqueda=termino_busqueda,
                           titulo_pagina="Lista de Clientes")

@main_bp.route('/clientes/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_cliente():
    """
    Maneja la creación de un nuevo cliente (Persona o Empresa).
    """
    if request.method == 'POST':
        try:
            # 1. Recoger datos del nuevo formulario
            tipo_documento = request.form.get('tipo_documento')
            numero_documento = request.form.get('numero_documento', '').strip() or None
            razon_social_nombres = request.form.get('razon_social_nombres')
            apellidos = request.form.get('apellidos', '').strip() or None
            direccion = request.form.get('direccion', '').strip() or None
            email = request.form.get('email', '').strip() or None
            telefono = request.form.get('telefono', '').strip() or None
            fecha_nacimiento_str = request.form.get('fecha_nacimiento')
            puntos_fidelidad = request.form.get('puntos_fidelidad', 0, type=int)

            # 2. Validaciones
            if not razon_social_nombres:
                raise ValueError("El campo Nombres/Razón Social es obligatorio.")
            if tipo_documento == 'DNI' and not apellidos:
                raise ValueError("El campo Apellidos es obligatorio para personas con DNI.")
            
            # Si es RUC, los apellidos se guardan como NULL
            if tipo_documento == 'RUC':
                apellidos = None

            fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None

            # 3. Guardar en la Base de Datos
            db = get_db()
            with db.cursor() as cursor:
                sql = """INSERT INTO clientes 
                            (tipo_documento, numero_documento, razon_social_nombres, apellidos, 
                             direccion, email, telefono, fecha_nacimiento, puntos_fidelidad) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                val = (tipo_documento, numero_documento, razon_social_nombres, apellidos, 
                       direccion, email, telefono, fecha_nacimiento, puntos_fidelidad)
                cursor.execute(sql, val)
                nuevo_cliente_id = cursor.lastrowid
                db.commit()
                
                # 4. Preparar mensaje de bienvenida por WhatsApp
                mensaje_exito = f'¡Cliente "{razon_social_nombres} {apellidos or ""}" registrado exitosamente!'
                if telefono:
                    telefono_limpio = ''.join(filter(str.isdigit, telefono))
                    if not telefono_limpio.startswith('51'): telefono_limpio = f'51{telefono_limpio}'
                    mensaje_whatsapp = f"Hola {razon_social_nombres.split(' ')[0]}, bienvenido a JV Studio. Gracias por registrarte con nosotros. Agenda tu cita pronto!"
                    enlace_whatsapp = f"https://wa.me/{telefono_limpio}?text={quote_plus(mensaje_whatsapp)}"
                    mensaje_exito += f' <a href="{enlace_whatsapp}" target="_blank" class="btn btn-success btn-sm ms-2"><i class="fab fa-whatsapp me-1"></i>Enviar Bienvenida</a>'

                flash(mensaje_exito, 'success')
            return redirect(url_for('main.listar_clientes'))

        except (ValueError, mysql.connector.Error) as e:
            get_db().rollback()
            flash(f"Error al registrar al cliente: {e}", "danger")
    
    # Lógica GET
    return render_template('clientes/form_cliente.html', 
                           es_nueva=True, 
                           titulo_form="Registrar Nuevo Cliente",
                           action_url=url_for('main.nuevo_cliente'),
                           form_data=request.form if request.method == 'POST' else None)
    
    
@main_bp.route('/clientes/ver/<int:cliente_id>')
@login_required
def ver_cliente(cliente_id):
    """
    Muestra los detalles de un cliente específico.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
        cliente_encontrado = cursor.fetchone()
        cursor.close()
        
        if cliente_encontrado is None:
            flash(f'Cliente con ID {cliente_id} no encontrado.', 'warning')
            return redirect(url_for('main.listar_clientes'))
            
    except mysql.connector.Error as err:
        flash(f"Error al acceder a la base de datos para ver cliente: {err}", "danger")
        current_app.logger.error(f"Error en ver_cliente (ID: {cliente_id}): {err}")
        return redirect(url_for('main.listar_clientes')) # Redirigir si hay error de BD

    return render_template('clientes/ver_cliente.html', cliente=cliente_encontrado)

@main_bp.route('/clientes/editar/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_cliente(cliente_id):
    db_conn = get_db()
    
    if request.method == 'POST':
        try:
            # 1. Recoger datos del formulario
            tipo_documento = request.form.get('tipo_documento')
            numero_documento = request.form.get('numero_documento', '').strip() or None
            razon_social_nombres = request.form.get('razon_social_nombres')
            apellidos = request.form.get('apellidos', '').strip() or None
            direccion = request.form.get('direccion', '').strip() or None
            email = request.form.get('email', '').strip() or None
            telefono = request.form.get('telefono', '').strip() or None
            fecha_nacimiento_str = request.form.get('fecha_nacimiento')
            puntos_fidelidad = request.form.get('puntos_fidelidad', 0, type=int)

            # 2. Validaciones
            if not razon_social_nombres:
                raise ValueError("El campo Nombres/Razón Social es obligatorio.")
            if tipo_documento == 'DNI' and not apellidos:
                raise ValueError("El campo Apellidos es obligatorio para personas con DNI.")
            if tipo_documento == 'RUC':
                apellidos = None
            
            fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None

            # 3. Actualizar en la base de datos
            with db_conn.cursor() as cursor:
                sql_update = """UPDATE clientes SET 
                                    tipo_documento=%s, numero_documento=%s, razon_social_nombres=%s, 
                                    apellidos=%s, direccion=%s, email=%s, telefono=%s, 
                                    fecha_nacimiento=%s, puntos_fidelidad=%s 
                                WHERE id=%s"""
                val_update = (
                    tipo_documento, numero_documento, razon_social_nombres, apellidos, direccion,
                    email, telefono, fecha_nacimiento, puntos_fidelidad, cliente_id
                )
                cursor.execute(sql_update, val_update)
            db_conn.commit()
            flash('Cliente actualizado exitosamente.', 'success')
            return redirect(url_for('main.listar_clientes'))

        except (ValueError, mysql.connector.Error) as e:
            db_conn.rollback()
            flash(f"Error al actualizar al cliente: {e}", "warning")
            return redirect(url_for('main.editar_cliente', cliente_id=cliente_id))
    
    # --- Lógica GET ---
    with db_conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
        cliente_actual = cursor.fetchone()
    
    if not cliente_actual:
        flash("Cliente no encontrado.", "warning")
        return redirect(url_for('main.listar_clientes'))
        
    if cliente_actual.get('fecha_nacimiento'):
        cliente_actual['fecha_nacimiento'] = cliente_actual['fecha_nacimiento'].strftime('%Y-%m-%d')
        
    return render_template('clientes/form_cliente.html', 
                           es_nueva=False, 
                           titulo_form=f"Editar Cliente: {cliente_actual.get('razon_social_nombres')}",
                           action_url=url_for('main.editar_cliente', cliente_id=cliente_id),
                           cliente=cliente_actual)

@main_bp.route('/clientes/eliminar/<int:cliente_id>', methods=['GET']) # Podría ser POST para más seguridad
@login_required
def eliminar_cliente(cliente_id):
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Opcional: Verificar si el cliente existe antes de intentar eliminar
        # cursor_check = db.cursor(dictionary=True)
        # cursor_check.execute("SELECT id FROM clientes WHERE id = %s", (cliente_id,))
        # cliente_a_eliminar = cursor_check.fetchone()
        # cursor_check.close()
        # if not cliente_a_eliminar:
        #     flash(f"Cliente con ID {cliente_id} no encontrado.", "warning")
        #     return redirect(url_for('main.listar_clientes'))

        # Eliminar referencias en otras tablas si existieran (ej. citas, ventas)
        # ¡IMPORTANTE! Si tienes claves foráneas (foreign keys) que apuntan a clientes
        # desde otras tablas (como 'reservas', 'ventas_productos'), necesitarás decidir
        # qué hacer:
        # 1. Eliminar esas filas dependientes primero.
        # 2. Configurar ON DELETE CASCADE / ON DELETE SET NULL en tus claves foráneas en MySQL.
        # 3. O impedir la eliminación si existen dependencias.
        # Por ahora, asumiremos que no hay dependencias bloqueantes o que están configuradas con ON DELETE CASCADE.

        sql = "DELETE FROM clientes WHERE id = %s"
        cursor.execute(sql, (cliente_id,))
        db.commit()
        
        if cursor.rowcount > 0:
            flash(f'Cliente con ID {cliente_id} eliminado exitosamente!', 'success')
        else:
            flash(f'No se encontró o no se pudo eliminar el cliente con ID {cliente_id}.', 'warning')
            
        cursor.close()

    except mysql.connector.Error as err:
        db.rollback()
        flash(f'Error al eliminar el cliente: {err}', 'danger')
        current_app.logger.error(f"Error DB en eliminar_cliente (ID: {cliente_id}): {err}")
        if '1451' in str(err): # Error específico de restricción de clave foránea
             flash('Este cliente no puede ser eliminado porque tiene registros asociados (ej. citas, ventas). Elimine esos registros primero.', 'warning')

    return redirect(url_for('main.listar_clientes'))

# --- RUTAS PARA LA GESTIÓN DE CATEGORÍAS DE SERVICIOS ---

@main_bp.route('/api/clientes/buscar_por_documento')
@login_required
def api_buscar_cliente_por_documento():
    """
    API para buscar un cliente existente por su número de documento.
    Versión corregida para usar la nueva estructura de la tabla 'clientes'.
    """
    numero_doc = request.args.get('numero_doc', '').strip()

    if not numero_doc:
        return jsonify({"error": "Se requiere un número de documento."}), 400

    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            # CORRECCIÓN: Buscamos en la columna 'numero_documento'
            # y seleccionamos las columnas con los nombres nuevos.
            sql = "SELECT id, razon_social_nombres, apellidos, numero_documento FROM clientes WHERE numero_documento = %s"
            cursor.execute(sql, (numero_doc,))
            cliente = cursor.fetchone()

            if cliente:
                return jsonify(cliente)
            else:
                return jsonify({"error": "No se encontró un cliente con ese documento."}), 404
    
    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_buscar_cliente_por_documento: {err}")
        return jsonify({"error": "Error interno al buscar el cliente."}), 500


@main_bp.route('/servicios/categorias')
@login_required
def listar_categorias_servicios():
    """
    Muestra la lista de todas las categorías de servicios.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_servicios ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las categorías: {err}", "danger")
        current_app.logger.error(f"Error en listar_categorias_servicios: {err}")
        lista_de_categorias = []
        
    return render_template('servicios/lista_categorias.html', categorias=lista_de_categorias)

@main_bp.route('/servicios/categorias/nueva', methods=['GET', 'POST'])
@login_required
def nueva_categoria_servicio():
    """
    Muestra el formulario para registrar una nueva categoría de servicio (GET)
    y procesa la creación de la categoría (POST).
    """
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')

        if not nombre:
            flash('El nombre de la categoría es obligatorio.', 'warning')
            return render_template('servicios/form_categoria.html', form_data=request.form, es_nueva=True, titulo_form="Nueva Categoría")

        try:
            db = get_db()
            cursor = db.cursor()
            sql = "INSERT INTO categorias_servicios (nombre, descripcion) VALUES (%s, %s)"
            val = (nombre, descripcion)
            cursor.execute(sql, val)
            db.commit()
            flash(f'Categoría "{nombre}" registrada exitosamente!', 'success')
            cursor.close()
            return redirect(url_for('main.listar_categorias_servicios'))
        except mysql.connector.Error as err:
            db.rollback()
            # Error 1062 es para entrada duplicada (nombre UNIQUE)
            if err.errno == 1062:
                flash(f'Error: Ya existe una categoría con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la categoría: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_categoria_servicio (POST): {err}")
            cursor.close()
            return render_template('servicios/form_categoria.html', form_data=request.form, es_nueva=True, titulo_form="Nueva Categoría")

    # Método GET: muestra el formulario vacío para una nueva categoría
    return render_template('servicios/form_categoria.html', es_nueva=True, titulo_form="Registrar Nueva Categoría de Servicio")

@main_bp.route('/servicios/categorias/editar/<int:categoria_id>', methods=['GET', 'POST'])
@login_required
def editar_categoria_servicio(categoria_id):
    """
    Muestra el formulario para editar una categoría existente (GET)
    y procesa la actualización de la categoría (POST).
    """
    # Obtener la categoría para asegurarse de que existe y para rellenar el formulario en GET
    try:
        db_check = get_db()
        cursor_check = db_check.cursor(dictionary=True)
        cursor_check.execute("SELECT id, nombre, descripcion FROM categorias_servicios WHERE id = %s", (categoria_id,))
        categoria_actual = cursor_check.fetchone()
        cursor_check.close()
    except mysql.connector.Error as err:
        flash(f"Error de base de datos al buscar la categoría: {err}", "danger")
        current_app.logger.error(f"Error DB en GET editar_categoria_servicio (ID: {categoria_id}): {err}")
        return redirect(url_for('main.listar_categorias_servicios'))

    if not categoria_actual:
        flash(f"Categoría con ID {categoria_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_categorias_servicios'))

    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre')
        descripcion_nueva = request.form.get('descripcion')

        if not nombre_nuevo:
            flash('El nombre de la categoría es obligatorio.', 'warning')
            # Volver a renderizar el formulario con los datos del POST y el error
            return render_template('servicios/form_categoria.html', 
                                   es_nueva=False, 
                                   titulo_form=f"Editar Categoría: {categoria_actual['nombre']}", 
                                   categoria=categoria_actual, 
                                   form_data=request.form)
        
        try:
            db = get_db()
            cursor = db.cursor()

            # Verificar si el nuevo nombre ya existe en otra categoría
            if nombre_nuevo.lower() != categoria_actual['nombre'].lower(): # Solo si el nombre ha cambiado
                cursor.execute("SELECT id FROM categorias_servicios WHERE nombre = %s AND id != %s", (nombre_nuevo, categoria_id))
                if cursor.fetchone():
                    flash(f'Error: Ya existe otra categoría con el nombre "{nombre_nuevo}".', 'danger')
                    db.rollback() # Asegurar que no haya transacciones pendientes si se hizo alguna otra consulta
                    cursor.close()
                    return render_template('servicios/form_categoria.html', 
                                           es_nueva=False, 
                                           titulo_form=f"Editar Categoría: {categoria_actual['nombre']}", 
                                           categoria=categoria_actual, 
                                           form_data=request.form)

            sql = "UPDATE categorias_servicios SET nombre = %s, descripcion = %s WHERE id = %s"
            val = (nombre_nuevo, descripcion_nueva, categoria_id)
            cursor.execute(sql, val)
            db.commit()
            flash(f'Categoría "{nombre_nuevo}" actualizada exitosamente!', 'success')
            cursor.close()
            return redirect(url_for('main.listar_categorias_servicios'))
        except mysql.connector.Error as err:
            db.rollback()
            flash(f'Error al actualizar la categoría: {err}', 'danger')
            current_app.logger.error(f"Error DB en POST editar_categoria_servicio (ID: {categoria_id}): {err}")
            cursor.close()
            return render_template('servicios/form_categoria.html', 
                                   es_nueva=False, 
                                   titulo_form=f"Editar Categoría: {categoria_actual['nombre']}", 
                                   categoria=categoria_actual, 
                                   form_data=request.form)

    # Método GET: muestra el formulario con los datos actuales de la categoría
    return render_template('servicios/form_categoria.html', 
                           es_nueva=False, 
                           titulo_form=f"Editar Categoría: {categoria_actual['nombre']}", 
                           categoria=categoria_actual)

@main_bp.route('/servicios/categorias/eliminar/<int:categoria_id>', methods=['GET']) # Usamos GET por la confirmación JS
@login_required
def eliminar_categoria_servicio(categoria_id):
    """
    Elimina una categoría de servicio existente.
    """
    try:
        db = get_db()
        cursor = db.cursor()

        # ** ¡IMPORTANTE! Consideración sobre servicios asociados: **
        # Antes de eliminar una categoría, idealmente deberías verificar si hay
        # servicios (de la futura tabla 'servicios') que pertenezcan a esta categoría.
        # Si los hay, podrías:
        # 1. Impedir la eliminación y mostrar un error.
        # 2. Eliminar también los servicios asociados (si la lógica de negocio lo permite y tienes ON DELETE CASCADE).
        # 3. Permitir la eliminación y poner la categoria_id de los servicios asociados a NULL (si es nullable).
        #
        # Ejemplo de cómo sería la verificación (requiere la tabla 'servicios'):
        # cursor.execute("SELECT COUNT(*) as count FROM servicios WHERE categoria_id = %s", (categoria_id,))
        # count_result = cursor.fetchone()
        # if count_result and count_result['count'] > 0: # Asumiendo que el cursor devuelve dict
        #     flash(f"No se puede eliminar la categoría porque tiene {count_result['count']} servicio(s) asociado(s).", "warning")
        #     cursor.close()
        #     return redirect(url_for('main.listar_categorias_servicios'))
        #
        # Por ahora, procederemos con la eliminación directa de la categoría,
        # pero ten esto en cuenta cuando implementemos los servicios.

        sql = "DELETE FROM categorias_servicios WHERE id = %s"
        cursor.execute(sql, (categoria_id,))
        db.commit()

        if cursor.rowcount > 0:
            flash(f'Categoría con ID {categoria_id} eliminada exitosamente!', 'success')
        else:
            flash(f'No se encontró o no se pudo eliminar la categoría con ID {categoria_id}. Puede que ya haya sido eliminada.', 'warning')
            
        cursor.close()

    except mysql.connector.Error as err:
        db.rollback() # Revertir en caso de error
        flash(f'Error al eliminar la categoría: {err}', 'danger')
        current_app.logger.error(f"Error DB en eliminar_categoria_servicio (ID: {categoria_id}): {err}")
        # Si el error es por una restricción de clave foránea (ej. servicios aún la usan)
        if '1451' in str(err): # Error MySQL 1451: Cannot delete or update a parent row: a foreign key constraint fails
             flash('Esta categoría no puede ser eliminada porque tiene registros asociados (probablemente servicios). Elimine o reasigne esos registros primero.', 'warning')


    return redirect(url_for('main.listar_categorias_servicios'))

# --- RUTAS PARA LA GESTIÓN DE SERVICIOS ---

@main_bp.route('/servicios')
@login_required
def listar_servicios():
    """
    Muestra la lista de todos los servicios, incluyendo el nombre de su categoría.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Usamos un JOIN para obtener el nombre de la categoría del servicio
        sql = """
            SELECT s.id, s.nombre, s.descripcion, s.duracion_minutos, s.precio, 
                   s.activo, cs.nombre as categoria_nombre, s.categoria_id
            FROM servicios s
            JOIN categorias_servicios cs ON s.categoria_id = cs.id
            ORDER BY s.nombre
        """
        cursor.execute(sql)
        lista_de_servicios = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los servicios: {err}", "danger")
        current_app.logger.error(f"Error en listar_servicios: {err}")
        lista_de_servicios = []
        
    return render_template('servicios/lista_servicios.html', servicios=lista_de_servicios)

@main_bp.route('/servicios/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_servicio():
    """
    Muestra el formulario para registrar un nuevo servicio (GET)
    y procesa la creación del servicio (POST).
    """
    # Para el GET, necesitamos cargar las categorías para el dropdown
    try:
        db_cat = get_db()
        cursor_cat = db_cat.cursor(dictionary=True)
        cursor_cat.execute("SELECT id, nombre FROM categorias_servicios ORDER BY nombre")
        categorias = cursor_cat.fetchall()
        # No cerramos la conexión principal (g.db) aquí, solo el cursor si es necesario.
        # teardown_db se encargará de cerrar g.db al final de la petición.
        cursor_cat.close() 
    except mysql.connector.Error as err:
        flash(f"Error al cargar categorías para el formulario: {err}", "danger")
        current_app.logger.error(f"Error cargando categorías en nuevo_servicio (GET): {err}")
        categorias = [] # Si hay error, el dropdown estará vacío pero la página cargará

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        duracion_minutos = request.form.get('duracion_minutos', type=int)
        precio = request.form.get('precio') # Se validará y convertirá a Decimal después
        categoria_id = request.form.get('categoria_id', type=int)
        # El campo 'activo' de un checkbox se envía si está marcado, no se envía si no.
        porcentaje_comision_extra_str = request.form.get('porcentaje_comision_extra')
        porcentaje_comision_extra = float(porcentaje_comision_extra_str) if porcentaje_comision_extra_str else None
        activo = 'activo' in request.form # True si 'activo' está en request.form, False si no.

        # Validaciones
        errores = []
        if not nombre:
            errores.append('El nombre del servicio es obligatorio.')
        if duracion_minutos is None or duracion_minutos <= 0:
            errores.append('La duración en minutos debe ser un número positivo.')
        if not precio:
            errores.append('El precio es obligatorio.')
        else:
            try:
                # Intentar convertir precio a un tipo numérico adecuado para DECIMAL
                # Se puede usar float() o Decimal() de la librería decimal
                precio_decimal = float(precio) # Ojo con la precisión de float para dinero. Decimal es mejor.
                if precio_decimal < 0:
                    errores.append('El precio no puede ser negativo.')
            except ValueError:
                errores.append('El precio debe ser un número válido.')
        if categoria_id is None:
            errores.append('Debe seleccionar una categoría.')

        if errores:
            for error in errores:
                flash(error, 'warning')
            return render_template('servicios/form_servicio.html', 
                                   form_data=request.form, 
                                   categorias=categorias,
                                   es_nuevo=True,
                                   titulo_form="Registrar Nuevo Servicio")
        
        try:
            db = get_db()
            cursor = db.cursor()
            sql = """INSERT INTO servicios 
                                (nombre, descripcion, duracion_minutos, precio, categoria_id, activo, porcentaje_comision_extra) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s)"""
            val = (nombre, (descripcion or None), duracion_minutos, precio, categoria_id, activo, porcentaje_comision_extra)
            cursor.execute(sql, val)
            db.commit()
            flash(f'Servicio "{nombre}" registrado exitosamente!', 'success')
            cursor.close()
            return redirect(url_for('main.listar_servicios'))
        except mysql.connector.Error as err:
            db.rollback()
            flash(f'Error al registrar el servicio: {err}', 'danger')
            current_app.logger.error(f"Error en nuevo_servicio (POST): {err}")
            cursor.close()
            return render_template('servicios/form_servicio.html', 
                                   form_data=request.form,
                                   categorias=categorias,
                                   es_nuevo=True,
                                   titulo_form="Registrar Nuevo Servicio")

    # Método GET: muestra el formulario vacío para un nuevo servicio
    return render_template('servicios/form_servicio.html', 
                           categorias=categorias, 
                           es_nuevo=True,
                           titulo_form="Registrar Nuevo Servicio")

@main_bp.route('/servicios/editar/<int:servicio_id>', methods=['GET', 'POST'])
@login_required
def editar_servicio(servicio_id):
    db_conn = get_db() # Obtener la conexión a la BD una vez

    # --- Obtener el servicio actual para editar ---
    servicio_actual = None
    cursor_servicio = db_conn.cursor(dictionary=True)
    try:
        cursor_servicio.execute("SELECT * FROM servicios WHERE id = %s", (servicio_id,))
        servicio_actual = cursor_servicio.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error de base de datos al buscar el servicio: {err}", "danger")
        current_app.logger.error(f"Error DB al buscar servicio en editar_servicio (ID: {servicio_id}): {err}")
        return redirect(url_for('main.listar_servicios'))
    finally:
        cursor_servicio.close() # Cerrar el cursor aquí

    if not servicio_actual:
        flash(f'Servicio con ID {servicio_id} no encontrado. No se puede editar.', 'warning')
        return redirect(url_for('main.listar_servicios'))

    # --- Obtener todas las categorías para el menú desplegable ---
    categorias = []
    cursor_categorias = db_conn.cursor(dictionary=True)
    try:
        cursor_categorias.execute("SELECT id, nombre FROM categorias_servicios ORDER BY nombre")
        categorias = cursor_categorias.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar las categorías para el formulario: {err}", "danger")
        current_app.logger.error(f"Error DB al cargar categorías en editar_servicio: {err}")
        # categorias se mantendrá como lista vacía, el formulario se mostrará con el dropdown vacío
    finally:
        cursor_categorias.close() # Cerrar el cursor aquí

    # --- Lógica para cuando se envía el formulario (POST) ---
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        duracion_minutos_str = request.form.get('duracion_minutos')
        precio_str = request.form.get('precio')
        categoria_id_str = request.form.get('categoria_id')
        porcentaje_comision_extra_str = request.form.get('porcentaje_comision_extra')
        porcentaje_comision_extra = float(porcentaje_comision_extra_str) if porcentaje_comision_extra_str else None
        activo = 'activo' in request.form # True si el checkbox 'activo' está marcado

        # Variables para almacenar los valores convertidos y validados
        duracion_minutos = None
        precio_decimal = None
        categoria_id = None
        errores = []

        # Validaciones
        if not nombre:
            errores.append('El nombre del servicio es obligatorio.')
        
        if not duracion_minutos_str:
            errores.append('La duración en minutos es obligatoria.')
        else:
            try:
                duracion_minutos = int(duracion_minutos_str)
                if duracion_minutos <= 0:
                    errores.append('La duración en minutos debe ser un número positivo.')
            except ValueError:
                errores.append('La duración en minutos debe ser un número entero.')

        if not precio_str:
            errores.append('El precio es obligatorio.')
        else:
            try:
                # Para dinero, es mejor usar Decimal: from decimal import Decimal; precio_decimal = Decimal(precio_str)
                # Por simplicidad, usamos float, pero ten cuidado con la precisión para cálculos financieros.
                precio_decimal = float(precio_str)
                if precio_decimal < 0:
                    errores.append('El precio no puede ser negativo.')
            except ValueError:
                errores.append('El precio debe ser un número válido (ej. 25.50).')
        
        if not categoria_id_str:
            errores.append('Debe seleccionar una categoría.')
        else:
            try:
                categoria_id = int(categoria_id_str)
            except ValueError:
                errores.append('La categoría seleccionada no es válida.')

        if errores:
            for error in errores:
                flash(error, 'warning')
            # Volver a mostrar el formulario con los datos ingresados y los errores
            return render_template('servicios/form_servicio.html', 
                                   form_data=request.form, # Datos que el usuario intentó enviar
                                   categorias=categorias,  # Lista de categorías para el dropdown
                                   servicio=servicio_actual, # Datos originales del servicio para el título, etc.
                                   es_nuevo=False,
                                   titulo_form=f"Editar Servicio: {servicio_actual['nombre']}")
        
        # Si no hay errores de validación, proceder a actualizar la BD
        cursor_update = None # Inicializar por si hay error antes de asignarlo
        try:
            with db_conn.cursor() as cursor:
                # 3. Actualizar la base de datos
                sql_update = """UPDATE servicios SET 
                                    nombre=%s, descripcion=%s, duracion_minutos=%s, precio=%s, 
                                    categoria_id=%s, activo=%s, porcentaje_comision_extra=%s 
                                WHERE id=%s"""
                val_update = (nombre, descripcion, duracion_minutos, precio_decimal, categoria_id, activo, porcentaje_comision_extra, servicio_id)
                cursor.execute(sql_update, val_update)
            db_conn.commit()
            flash(f'Servicio "{nombre}" actualizado exitosamente.', 'success')
            return redirect(url_for('main.listar_servicios'))
            
        except mysql.connector.Error as err:
            db_conn.rollback() # Revertir cambios en caso de error de BD
            flash(f'Error al actualizar el servicio: {err}', 'danger')
            current_app.logger.error(f"Error DB en POST editar_servicio (ID: {servicio_id}): {err}")
            # Volver al formulario de edición
            return render_template('servicios/form_servicio.html', 
                                   form_data=request.form,
                                   categorias=categorias,
                                   servicio=servicio_actual,
                                   es_nuevo=False,
                                   titulo_form=f"Editar Servicio: {servicio_actual['nombre']}")
        finally:
            if cursor_update:
                cursor_update.close() # Cerrar el cursor de actualización

    # --- Método GET: Mostrar el formulario con los datos del servicio ---
    # Los cursores cursor_servicio y cursor_categorias ya fueron cerrados en sus bloques finally.
    return render_template('servicios/form_servicio.html', 
                           servicio=servicio_actual, # Datos del servicio para rellenar el formulario
                           categorias=categorias,    # Lista de categorías para el dropdown
                           es_nuevo=False,           # Indicar que no es un formulario nuevo
                           titulo_form=f"Editar Servicio: {servicio_actual['nombre']}")

@main_bp.route('/servicios/toggle_activo/<int:servicio_id>', methods=['GET'])
@login_required
def toggle_activo_servicio(servicio_id):
    """
    Cambia el estado 'activo' de un servicio (de True a False o viceversa).
    """
    servicio_actual = None
    db_conn = get_db()
    
    # Declarar cursores fuera del try para que estén disponibles en finally
    cursor_read = None
    cursor_update = None

    try:
        # Primero, obtener el estado actual del servicio
        cursor_read = db_conn.cursor(dictionary=True)
        cursor_read.execute("SELECT id, nombre, activo FROM servicios WHERE id = %s", (servicio_id,))
        servicio_actual = cursor_read.fetchone()

        if not servicio_actual:
            flash(f'Servicio con ID {servicio_id} no encontrado.', 'warning')
            return redirect(url_for('main.listar_servicios'))

        nuevo_estado_activo = not servicio_actual['activo'] # Invertir el estado
        
        cursor_update = db_conn.cursor() # Cursor para la operación de escritura
        sql_update = "UPDATE servicios SET activo = %s WHERE id = %s"
        cursor_update.execute(sql_update, (nuevo_estado_activo, servicio_id))
        db_conn.commit()
        
        mensaje_estado = "activado" if nuevo_estado_activo else "desactivado"
        flash(f'El servicio "{servicio_actual["nombre"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn: # Solo hacer rollback si la conexión existe
            db_conn.rollback()
        flash(f'Error al cambiar el estado del servicio: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_servicio (ID: {servicio_id}): {err}")
    finally:
        if cursor_read:
            cursor_read.close() 
        if cursor_update:
            cursor_update.close()

    return redirect(url_for('main.listar_servicios'))

# --- RUTAS PARA LA GESTIÓN DE EMPLEADOS ---

@main_bp.route('/empleados')
@login_required
@admin_required
def listar_empleados():
    """
    Muestra la lista de todos los colaboradores con el formato de fecha corregido.
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            # Consulta SQL con el formato de fecha corregido (%%)
            sql = """
                SELECT 
                    e.id, e.nombres, e.apellidos, e.nombre_display, e.dni, 
                    e.email, e.telefono, e.activo, e.sueldo_base,
                    DATE_FORMAT(e.fecha_contratacion, '%%d/%%m/%%Y') as fecha_contratacion_formateada,
                    s.nombre AS sucursal_nombre,
                    r.nombre AS rol_nombre
                FROM empleados e
                LEFT JOIN sucursales s ON e.sucursal_id = s.id
                LEFT JOIN roles r ON e.rol_id = r.id
                ORDER BY e.apellidos, e.nombres
            """
            cursor.execute(sql)
            lista_de_empleados = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los colaboradores: {err}", "danger")
        current_app.logger.error(f"Error en listar_empleados: {err}")
        lista_de_empleados = []
        
    return render_template('empleados/lista_empleados.html', empleados=lista_de_empleados)

@main_bp.route('/empleados/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_empleado():
    """
    Muestra el formulario para registrar un nuevo colaborador (GET)
    y procesa la creación con todos los nuevos campos (POST).
    """
    db_conn = get_db()
    
    # Cargar sucursales activas para el dropdown (necesario para GET y POST con error)
    sucursales_activas = []
    cursor_sucursales = None
    try:
        cursor_sucursales = db_conn.cursor(dictionary=True)
        cursor_sucursales.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor_sucursales.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar sucursales: {err_load}", "danger")
        current_app.logger.error(f"Error DB cargando sucursales en nuevo_empleado: {err_load}")
    finally:
        if cursor_sucursales: cursor_sucursales.close()


    form_titulo = "Registrar Nuevo Colaborador"
    action_url_form = url_for('main.nuevo_empleado')

    if request.method == 'POST':
        # Recoger todos los campos del formulario
        nombres = request.form.get('nombres')
        apellidos = request.form.get('apellidos')
        nombre_display = request.form.get('nombre_display', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        email = request.form.get('email', '').strip()
        telefono = request.form.get('telefono', '').strip()
        rol = request.form.get('rol')
        sueldo_base_str = request.form.get('sueldo_base')
        sucursal_id_str = request.form.get('sucursal_id')
        fecha_contratacion_str = request.form.get('fecha_contratacion')
        activo = 'activo' in request.form
        notas = request.form.get('notas')

        # Validaciones
        errores = []
        if not nombres: errores.append('El nombre es obligatorio.')
        if not apellidos: errores.append('Los apellidos son obligatorios.')
        if not rol: errores.append('El rol es obligatorio.')
        
        # Si no se proporciona nombre_display, se puede autogenerar
        if not nombre_display:
            primer_nombre = nombres.split(' ')[0]
            primer_apellido = apellidos.split(' ')[0]
            nombre_display = f"{primer_nombre} {primer_apellido}"
            
        # Convertir y validar datos
        fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None
        fecha_contratacion = datetime.strptime(fecha_contratacion_str, '%Y-%m-%d').date() if fecha_contratacion_str else None
        sucursal_id = int(sucursal_id_str) if sucursal_id_str else None
        dni_db = dni if dni else None
        email_db = email if email else None
        sueldo_base = float(sueldo_base_str) if sueldo_base_str else 0.00

        # Verificar unicidad de DNI si se proporcionó
        if dni_db:
            cursor_check = None
            try:
                cursor_check = db_conn.cursor(dictionary=True)
                cursor_check.execute("SELECT id FROM empleados WHERE dni = %s", (dni_db,))
                if cursor_check.fetchone():
                    errores.append(f"El DNI '{dni_db}' ya está registrado.")
            except mysql.connector.Error as err_check_dni:
                errores.append("Error al verificar el DNI.")
                current_app.logger.error(f"Error DB verificando DNI: {err_check_dni}")
            finally:
                if cursor_check: cursor_check.close()
        
        # El email ya es UNIQUE en la BD, así que la BD lo validará.
        # Podríamos añadir una comprobación aquí también como hicimos para el DNI si queremos un mensaje más amigable.

        if errores:
            for error in errores:
                flash(error, 'warning')
            # Volvemos a renderizar con los datos y errores
            return render_template('empleados/form_empleado.html', 
                                   form_data=request.form, 
                                   sucursales=sucursales_activas,
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        
        # Si todo es válido, proceder con la inserción
        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            sql = """INSERT INTO empleados 
                        (nombres, apellidos, nombre_display, dni, fecha_nacimiento, email, telefono, 
                         rol, sueldo_base, sucursal_id, fecha_contratacion, activo, notas, contrato_id)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            val = (nombres, apellidos, nombre_display, dni_db, fecha_nacimiento, email_db, 
                   (telefono if telefono else None), rol, sueldo_base, sucursal_id, 
                   fecha_contratacion, activo, (notas if notas else None), None)
            cursor_insert.execute(sql, val)
            db_conn.commit()
            flash(f'Colaborador {nombres} {apellidos} registrado exitosamente!', 'success')
            return redirect(url_for('main.listar_empleados'))
        except mysql.connector.Error as err:
            db_conn.rollback()
            if err.errno == 1062: # Error de entrada duplicada
                if 'dni' in err.msg:
                    flash(f'Error: Ya existe un colaborador con el DNI "{dni_db}".', 'danger')
                elif 'email' in err.msg:
                     flash(f'Error: Ya existe un colaborador con el email "{email_db}".', 'danger')
                else:
                    flash(f'Error de dato duplicado: {err.msg}', 'danger')
            else:
                flash(f'Error al registrar al colaborador: {err}', 'danger')
            current_app.logger.error(f"Error en nuevo_empleado (POST): {err}")
            # Volver a renderizar con los datos y errores
            return render_template('empleados/form_empleado.html', 
                                   form_data=request.form, 
                                   sucursales=sucursales_activas,
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('empleados/form_empleado.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           sucursales=sucursales_activas)


@main_bp.route('/empleados/editar/<int:empleado_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_empleado(empleado_id):
    """
    Maneja la edición de un colaborador con una estructura robusta para evitar errores.
    """
    db_conn = get_db()
    
    # --- PASO 1: Obtener el colaborador a editar. Si no se encuentra, no se puede continuar. ---
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM empleados WHERE id = %s", (empleado_id,))
            colaborador_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error de base de datos al buscar al colaborador: {err}", "danger")
        return redirect(url_for('main.listar_empleados'))

    if not colaborador_actual:
        flash(f"Colaborador con ID {empleado_id} no encontrado.", "warning")
        return redirect(url_for('main.listar_empleados'))

    # --- PASO 2: Si el método es POST, procesar los datos del formulario ---
    if request.method == 'POST':
        try:
            # Recoger todos los datos del formulario
            nombres = request.form.get('nombres')
            apellidos = request.form.get('apellidos')
            nombre_display = request.form.get('nombre_display', '').strip()
            dni_nuevo = request.form.get('dni', '').strip() or None
            fecha_nacimiento_str = request.form.get('fecha_nacimiento')
            email_nuevo = request.form.get('email', '').strip() or None
            telefono = request.form.get('telefono', '').strip() or None
            rol_id = request.form.get('rol_id', type=int)
            sueldo_base_str = request.form.get('sueldo_base')
            sucursal_id_str = request.form.get('sucursal_id')
            fecha_contratacion_str = request.form.get('fecha_contratacion')
            activo_nuevo = 'activo' in request.form
            notas = request.form.get('notas', '').strip() or None
            password_nuevo = request.form.get('password_nuevo')
            password_confirmacion = request.form.get('password_confirmacion')

            # Validaciones
            errores = []
            if not all([nombres, apellidos, rol_id]):
                errores.append("Nombres, Apellidos y Rol son campos obligatorios.")

            # Validar unicidad (DNI y Email) si han cambiado
            if dni_nuevo and dni_nuevo != colaborador_actual.get('dni'):
                with db_conn.cursor(dictionary=True) as cursor_check:
                    cursor_check.execute("SELECT id FROM empleados WHERE dni = %s AND id != %s", (dni_nuevo, empleado_id))
                    if cursor_check.fetchone():
                        errores.append(f"El DNI '{dni_nuevo}' ya está registrado.")
            
            if email_nuevo and email_nuevo.lower() != (colaborador_actual.get('email') or '').lower():
                 with db_conn.cursor(dictionary=True) as cursor_check:
                    cursor_check.execute("SELECT id FROM empleados WHERE email = %s AND id != %s", (email_nuevo, empleado_id))
                    if cursor_check.fetchone():
                        errores.append(f"El email '{email_nuevo}' ya está registrado.")

            # Validación de contraseña
            password_hash_para_guardar = None
            if password_nuevo:
                if password_nuevo != password_confirmacion:
                    errores.append("Las contraseñas no coinciden.")
                elif len(password_nuevo) < 8:
                    errores.append("La contraseña debe tener al menos 8 caracteres.")
                else:
                    password_hash_para_guardar = generate_password_hash(password_nuevo)
            
            if errores: raise ValueError("; ".join(errores))

            # Construir la consulta UPDATE
            sql_base = "UPDATE empleados SET nombres = %s, apellidos = %s, nombre_display = %s, dni = %s, fecha_nacimiento = %s, email = %s, telefono = %s, rol_id = %s, sueldo_base = %s, sucursal_id = %s, fecha_contratacion = %s, activo = %s, notas = %s"
            valores = [nombres, apellidos, (nombre_display or None), dni_nuevo, (fecha_nacimiento_str or None), email_nuevo, telefono, rol_id, (float(sueldo_base_str) if sueldo_base_str else 0.00), (int(sucursal_id_str) if sucursal_id_str else None), (fecha_contratacion_str or None), activo_nuevo, notas]
            if password_hash_para_guardar:
                sql_base += ", password = %s"
                valores.append(password_hash_para_guardar)
            
            sql_final = sql_base + " WHERE id = %s"
            valores.append(empleado_id)
            
            with db_conn.cursor() as cursor_update:
                cursor_update.execute(sql_final, tuple(valores))
            
            db_conn.commit()
            flash('Colaborador actualizado exitosamente!', 'success')
            return redirect(url_for('main.listar_empleados'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            db_conn.rollback()
            # Si hay un error, se lo mostramos al usuario y el código continuará para re-renderizar el formulario
            if isinstance(e, ValueError):
                for error_msg in errores: flash(error_msg, "warning")
            else:
                flash(f"Error al actualizar al colaborador: {e}", "danger")
            current_app.logger.error(f"Error en editar_empleado (POST): {e}")
            # Si hay error, el código caerá al render_template de abajo
    
    # --- Lógica GET (y para re-renderizar si POST falla) ---
    with db_conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM empleados WHERE id = %s", (empleado_id,))
        colaborador_a_editar = cursor.fetchone()
    if not colaborador_a_editar: # Doble chequeo
        return redirect(url_for('main.listar_empleados'))
        
    roles_disponibles, sucursales_activas = [], []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM roles ORDER BY nombre")
            roles_disponibles = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar datos del formulario: {e}", "danger")

    # Formatear fechas para los inputs del formulario
    if colaborador_actual.get('fecha_nacimiento'):
        colaborador_actual['fecha_nacimiento'] = colaborador_actual['fecha_nacimiento'].strftime('%Y-%m-%d')
    if colaborador_actual.get('fecha_contratacion'):
        colaborador_actual['fecha_contratacion'] = colaborador_actual['fecha_contratacion'].strftime('%Y-%m-%d')
        
    return render_template('empleados/form_empleado.html', 
                           es_nueva=False, 
                           titulo_form=f"Editar Colaborador: {colaborador_actual.get('nombres')}",
                           action_url=url_for('main.editar_empleado', empleado_id=empleado_id),
                           empleado=colaborador_actual,
                           sucursales=sucursales_activas,
                           roles=roles_disponibles,
                           # Si venimos de un POST fallido, rellenamos el form con los datos que fallaron
                           form_data=request.form if request.method == 'POST' else None)
                            

@main_bp.route('/empleados/toggle_activo/<int:empleado_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_empleado(empleado_id):
    """
    Cambia el estado 'activo' de un empleado.
    """
    empleado_actual = None
    db_conn = get_db()
    cursor_read = None
    cursor_update = None

    try:
        cursor_read = db_conn.cursor(dictionary=True)
        cursor_read.execute("SELECT id, nombres, apellidos, activo FROM empleados WHERE id = %s", (empleado_id,))
        empleado_actual = cursor_read.fetchone()

        if not empleado_actual:
            flash(f'Empleado con ID {empleado_id} no encontrado.', 'warning')
            return redirect(url_for('main.listar_empleados'))

        nuevo_estado_activo = not empleado_actual['activo']
        
        # Cerramos el cursor de lectura ya que no se necesita más
        if cursor_read:
            cursor_read.close()
            cursor_read = None 

        cursor_update = db_conn.cursor()
        sql_update = "UPDATE empleados SET activo = %s WHERE id = %s"
        cursor_update.execute(sql_update, (nuevo_estado_activo, empleado_id))
        db_conn.commit()
        
        mensaje_estado = "activado" if nuevo_estado_activo else "desactivado"
        flash(f'El empleado {empleado_actual["nombres"]} {empleado_actual["apellidos"]} ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f'Error al cambiar el estado del empleado: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_empleado (ID: {empleado_id}): {err}")
    finally:
        if cursor_read: # Por si hubo una excepción antes de cerrarlo explícitamente
            cursor_read.close() 
        if cursor_update:
            cursor_update.close()

    return redirect(url_for('main.listar_empleados'))


@main_bp.route('/colaboradores/<int:colaborador_id>/cuotas', methods=['GET', 'POST'])
@login_required
@admin_required
def gestionar_cuotas(colaborador_id):
    """
    Muestra la página para ver y añadir cuotas mensuales (por valor o cantidad)
    para un colaborador específico.
    """
    db_conn = get_db()
    
    # --- Lógica POST (cuando se guarda una nueva cuota) ---
    if request.method == 'POST':
        try:
            anio = request.form.get('anio', type=int)
            mes = request.form.get('mes', type=int)
            tipo_cuota = request.form.get('tipo_cuota')
            valor_objetivo_cuota = request.form.get('valor_objetivo_cuota', type=float)
            tipo_bono = request.form.get('tipo_bono')
            valor_bono = request.form.get('valor_bono', type=float)

            if not all([anio, mes, tipo_cuota, valor_objetivo_cuota is not None, tipo_bono, valor_bono is not None]):
                raise ValueError("Todos los campos del formulario son obligatorios.")

            with db_conn.cursor() as cursor:
                sql = """INSERT INTO cuotas_mensuales 
                            (colaborador_id, anio, mes, tipo_cuota, valor_objetivo_cuota, tipo_bono, valor_bono) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s)"""
                cursor.execute(sql, (colaborador_id, anio, mes, tipo_cuota, valor_objetivo_cuota, tipo_bono, valor_bono))
                db_conn.commit()
                flash(f"Cuota para {mes}/{anio} registrada exitosamente.", "success")
        except mysql.connector.Error as err:
            db_conn.rollback()
            if err.errno == 1062:
                flash(f"Error: Ya existe una cuota para este colaborador en {mes}/{anio}.", "danger")
            else:
                flash(f"Error de base de datos: {err}", "danger")
        except ValueError as ve:
            flash(f"Error de validación: {ve}", "warning")
        
        return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

    # --- Lógica GET (para mostrar la página) ---
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
            colaborador = cursor.fetchone()
            if not colaborador:
                flash("Colaborador no encontrado.", "warning")
                return redirect(url_for('main.listar_empleados'))

            cursor.execute("SELECT * FROM cuotas_mensuales WHERE colaborador_id = %s ORDER BY anio DESC, mes DESC", (colaborador_id,))
            cuotas_registradas = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar la página de cuotas: {err}", "danger")
        return redirect(url_for('main.listar_empleados'))

    return render_template('empleados/gestionar_cuotas.html',
                           colaborador=colaborador,
                           cuotas=cuotas_registradas,
                           anio_actual=datetime.now().year,
                           titulo_pagina=f"Cuotas de Producción para {colaborador['nombres']}")

@main_bp.route('/colaboradores/<int:colaborador_id>/cuotas/nueva', methods=['POST'])
@login_required
@admin_required
def agregar_cuota(colaborador_id):
    """
    Procesa el formulario para añadir una nueva cuota mensual.
    """
    anio = request.form.get('anio', type=int)
    mes = request.form.get('mes', type=int)
    monto = request.form.get('monto_cuota', type=float)

    if not all([anio, mes, monto]):
        flash("Todos los campos (Año, Mes, Monto) son obligatorios.", "warning")
        return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

    if not (2020 <= anio <= 2050 and 1 <= mes <= 12 and monto >= 0):
        flash("Por favor, ingrese valores válidos.", "warning")
        return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            sql = "INSERT INTO cuotas_mensuales (colaborador_id, anio, mes, monto_cuota) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (colaborador_id, anio, mes, monto))
            db_conn.commit()
            flash(f"Cuota para {mes}/{anio} registrada exitosamente.", "success")
    except mysql.connector.Error as err:
        db_conn.rollback()
        if err.errno == 1062: # Error de constraint UNIQUE
            flash(f"Error: Ya existe una cuota registrada para este colaborador en el mes {mes}/{anio}.", "danger")
        else:
            flash(f"Error de base de datos al guardar la cuota: {err}", "danger")
    
    return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

@main_bp.route('/colaboradores/<int:colaborador_id>/cuotas/editar/<int:cuota_id>', methods=['POST'])
@login_required
@admin_required
def editar_cuota(colaborador_id, cuota_id):
    """
    Procesa la edición de una cuota mensual existente.
    """
    anio = request.form.get('anio', type=int)
    mes = request.form.get('mes', type=int)
    monto = request.form.get('monto_cuota', type=float)

    if not all([anio, mes, monto]) or monto < 0:
        flash("Datos inválidos. Verifique la información.", "warning")
        return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            # Opcional: verificar que la nueva combinación de año y mes no exista ya para este colaborador (excluyendo la cuota actual)
            cursor.execute("SELECT id FROM cuotas_mensuales WHERE colaborador_id = %s AND anio = %s AND mes = %s AND id != %s", 
                           (colaborador_id, anio, mes, cuota_id))
            if cursor.fetchone():
                flash(f"Error: Ya existe una cuota para {mes}/{anio}.", "danger")
                return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

            # Actualizar la cuota
            sql = "UPDATE cuotas_mensuales SET anio = %s, mes = %s, monto_cuota = %s WHERE id = %s AND colaborador_id = %s"
            cursor.execute(sql, (anio, mes, monto, cuota_id, colaborador_id))
            db_conn.commit()
            flash("Cuota actualizada exitosamente.", "success")
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al actualizar la cuota: {err}", "danger")

    return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

@main_bp.route('/colaboradores/<int:colaborador_id>/cuotas/eliminar/<int:cuota_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_cuota(colaborador_id, cuota_id):
    """
    Elimina un registro de cuota mensual.
    """
    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            cursor.execute("DELETE FROM cuotas_mensuales WHERE id = %s AND colaborador_id = %s", (cuota_id, colaborador_id))
            db_conn.commit()
            if cursor.rowcount > 0:
                flash("Cuota eliminada exitosamente.", "success")
            else:
                flash("No se encontró la cuota a eliminar.", "warning")
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al eliminar la cuota: {err}", "danger")
    
    return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))


# AJUSTES DE SUELDOS DE COLABORADORES 
@main_bp.route('/colaboradores/<int:colaborador_id>/ajustes', methods=['GET'])
@login_required
@admin_required
def gestionar_ajustes(colaborador_id):
    """
    Muestra la página para ver y añadir ajustes de pago para un colaborador.
    """
    db_conn = get_db()
    with db_conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
        colaborador = cursor.fetchone()
        if not colaborador:
            flash("Colaborador no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        cursor.execute("SELECT *, DATE_FORMAT(fecha, '%d/%m/%Y') as fecha_formateada FROM ajustes_pago WHERE colaborador_id = %s ORDER BY fecha DESC, id DESC", (colaborador_id,))
        ajustes_registrados = cursor.fetchall()
        
    return render_template('empleados/gestionar_ajustes.html',
                           colaborador=colaborador,
                           ajustes=ajustes_registrados,
                           titulo_pagina=f"Ajustes de Pago para {colaborador['nombres']}")

@main_bp.route('/colaboradores/<int:colaborador_id>/ajustes/nueva', methods=['POST'])
@login_required
@admin_required
def agregar_ajuste(colaborador_id):
    """
    Procesa el formulario para añadir un nuevo ajuste de pago.
    """
    fecha = request.form.get('fecha')
    tipo = request.form.get('tipo')
    monto_str = request.form.get('monto')
    descripcion = request.form.get('descripcion')
    es_descuento = 'es_descuento' in request.form # Checkbox para saber si es negativo

    if not all([fecha, tipo, monto_str, descripcion]):
        flash("Todos los campos son obligatorios.", "warning")
        return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))

    try:
        monto = float(monto_str)
        if monto < 0:
            raise ValueError("El monto no puede ser negativo. Use la casilla de descuento.")
        
        # Si se marca la casilla "Es Descuento", convertimos el monto a negativo
        if es_descuento:
            monto = -monto

    except (ValueError, TypeError):
        flash("El monto debe ser un número válido.", "warning")
        return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))

    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            # El estado por defecto es 'Pendiente'
            sql = "INSERT INTO ajustes_pago (colaborador_id, fecha, tipo, monto, descripcion) VALUES (%s, %s, %s, %s, %s)"
            cursor.execute(sql, (colaborador_id, fecha, tipo, monto, descripcion))
            db_conn.commit()
            flash("Ajuste de pago registrado exitosamente.", "success")
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al guardar el ajuste: {err}", "danger")
    
    return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))

@main_bp.route('/colaboradores/<int:colaborador_id>/ajustes/editar/<int:ajuste_id>', methods=['POST'])
@login_required
@admin_required
def editar_ajuste(colaborador_id, ajuste_id):
    """
    Procesa la edición de un ajuste de pago existente.
    """
    fecha = request.form.get('fecha')
    tipo = request.form.get('tipo')
    monto_str = request.form.get('monto')
    descripcion = request.form.get('descripcion')
    es_descuento = 'es_descuento' in request.form

    if not all([fecha, tipo, monto_str, descripcion]):
        flash("Todos los campos son obligatorios.", "warning")
        return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))

    try:
        monto = float(monto_str)
        if monto < 0: raise ValueError("Monto inválido.")
        if es_descuento: monto = -monto
    except (ValueError, TypeError):
        flash("El monto debe ser un número válido y positivo.", "warning")
        return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))

    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            # Solo se pueden editar ajustes en estado 'Pendiente'
            sql = "UPDATE ajustes_pago SET fecha=%s, tipo=%s, monto=%s, descripcion=%s WHERE id=%s AND colaborador_id=%s AND estado='Pendiente'"
            cursor.execute(sql, (fecha, tipo, monto, descripcion, ajuste_id, colaborador_id))
            if cursor.rowcount == 0:
                flash("El ajuste no se pudo actualizar (puede que ya no esté pendiente o no exista).", "warning")
            else:
                db_conn.commit()
                flash("Ajuste actualizado exitosamente.", "success")
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al actualizar el ajuste: {err}", "danger")
    
    return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))


@main_bp.route('/colaboradores/<int:colaborador_id>/ajustes/eliminar/<int:ajuste_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_ajuste(colaborador_id, ajuste_id):
    """
    Elimina un registro de ajuste de pago, solo si está pendiente.
    """
    try:
        db_conn = get_db()
        with db_conn.cursor() as cursor:
            # Por seguridad, solo eliminamos ajustes en estado 'Pendiente'
            cursor.execute("DELETE FROM ajustes_pago WHERE id = %s AND colaborador_id = %s AND estado = 'Pendiente'", (ajuste_id, colaborador_id))
            db_conn.commit()
            if cursor.rowcount > 0:
                flash("Ajuste eliminado exitosamente.", "success")
            else:
                flash("No se encontró el ajuste o no se pudo eliminar (puede que ya haya sido aplicado).", "warning")
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al eliminar el ajuste: {err}", "danger")
    
    return redirect(url_for('main.gestionar_ajustes', colaborador_id=colaborador_id))



# --- RUTAS PARA LA GESTIÓN DE RESERVAS ---

@main_bp.route('/reservas')
@login_required
def listar_reservas():
    db = get_db()
    lista_de_reservas = []
    clientes_todos, empleados_para_selector, servicios_todos_activos = [], [], []
    
    try:
        with db.cursor(dictionary=True) as cursor:
            # Obtener lista de reservas (sin cambios)
            sql = "SELECT r.id, DATE_FORMAT(r.fecha_hora_inicio, '%d/%m/%Y %H:%i') as fecha_hora, CONCAT(c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) AS cliente_nombre, e.nombre_display AS empleado_nombre, s.nombre AS servicio_nombre, r.precio_cobrado, r.estado FROM reservas r LEFT JOIN clientes c ON r.cliente_id = c.id JOIN empleados e ON r.empleado_id = e.id JOIN servicios s ON r.servicio_id = s.id ORDER BY r.fecha_hora_inicio DESC"
            cursor.execute(sql)
            lista_de_reservas = cursor.fetchall()

            # Obtener listas para los modales
            cursor.execute("SELECT id, razon_social_nombres, apellidos FROM clientes ORDER BY razon_social_nombres, apellidos")
            clientes_todos = cursor.fetchall()
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            empleados_para_selector = cursor.fetchall()
            cursor.execute("SELECT id, nombre, duracion_minutos FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_todos_activos = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al acceder a las reservas: {err}", "danger")

    return render_template('reservas/lista_reservas.html', 
                           reservas=lista_de_reservas,
                           clientes_todos=clientes_todos,
                           empleados_para_selector=empleados_para_selector,
                           servicios_todos_activos=servicios_todos_activos)


@main_bp.route('/reservas/agenda')
@login_required
def render_agenda_diaria():
    """
    Renderiza la página principal de la nueva agenda con FullCalendar.
    """
    db_conn = get_db()
    sucursales_para_selector, clientes_todos, servicios_todos_activos, empleados_para_selector = [], [], [], []
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_para_selector = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, razon_social_nombres, apellidos FROM clientes WHERE tipo_documento != 'RUC' OR tipo_documento IS NULL ORDER BY razon_social_nombres, apellidos")
            clientes_todos = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, precio, duracion_minutos FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_todos_activos = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos, sucursal_id, nombre_display FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            empleados_para_selector = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error fatal al cargar datos maestros para la agenda: {err_load}", "danger")
    
    return render_template('reservas/agenda_diaria.html', 
                           sucursales_para_selector=sucursales_para_selector,
                           clientes_todos=clientes_todos,
                           servicios_todos_activos=servicios_todos_activos,
                           empleados_para_selector=empleados_para_selector)
    
    
@main_bp.route('/api/reservas/<int:reserva_id>')
@login_required
def api_get_datos_reserva(reserva_id):
    """
    API para obtener los detalles completos de una reserva específica
    para mostrar en el modal de gestión.
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            # Consulta actualizada para usar la nueva estructura de la tabla 'clientes'
            sql = """
                SELECT r.*, s.nombre as servicio_nombre, e.nombre_display as empleado_nombre_completo,
                    CONCAT(c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) as cliente_nombre_completo
                FROM reservas r
                LEFT JOIN clientes c ON r.cliente_id = c.id
                JOIN servicios s ON r.servicio_id = s.id
                JOIN empleados e ON r.empleado_id = e.id
                WHERE r.id = %s
            """
            cursor.execute(sql, (reserva_id,))
            reserva = cursor.fetchone()

            if reserva:
                # Formatear las fechas a un string estándar ISO para JavaScript
                if reserva.get('fecha_hora_inicio'):
                    reserva['fecha_hora_inicio'] = reserva['fecha_hora_inicio'].isoformat()
                if reserva.get('fecha_hora_fin'):
                    reserva['fecha_hora_fin'] = reserva['fecha_hora_fin'].isoformat()
                
                return jsonify(reserva)
            else:
                return jsonify({"error": "Reserva no encontrada."}), 404
    
    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_get_datos_reserva: {err}")
        return jsonify({"error": "Error interno al buscar la reserva."}), 500


@main_bp.route('/api/agenda_dia_data')
@login_required
def api_agenda_dia_data():
    """
    Devuelve datos para FullCalendar, tratando todos los fondos (turnos, ausencias) como eventos.
    """
    fecha_str = request.args.get('fecha', date.today().isoformat())
    sucursal_id = request.args.get('sucursal_id', type=int)
    fecha_obj = date.fromisoformat(fecha_str)
    
    if not sucursal_id:
        return jsonify({"recursos": [], "eventos": []})

    try:
        db_conn = get_db()
        with db_conn.cursor(dictionary=True) as cursor:
            # 1. Obtener los colaboradores (Recursos)
            cursor.execute("SELECT id, nombre_display as title FROM empleados WHERE activo = TRUE AND sucursal_id = %s ORDER BY nombres", (sucursal_id,))
            recursos = cursor.fetchall()
            
            eventos = []
            if recursos:
                recursos_ids = [r['id'] for r in recursos]
                placeholders = ','.join(['%s'] * len(recursos_ids))
                
                # 2. Obtener Turnos de Trabajo y convertirlos en EVENTOS de fondo verdes
                dia_semana_num = fecha_obj.isoweekday()
                sql_turnos = f"SELECT empleado_id, hora_inicio, hora_fin FROM horarios_empleado WHERE empleado_id IN ({placeholders}) AND dia_semana = %s"
                cursor.execute(sql_turnos, tuple(recursos_ids) + (dia_semana_num,))
                for turno in cursor.fetchall():
                    eventos.append({
                        "resourceId": turno['empleado_id'],
                        "start": f"{fecha_str}T{timedelta_to_hhmm_str(turno['hora_inicio'])}",
                        "end": f"{fecha_str}T{timedelta_to_hhmm_str(turno['hora_fin'])}",
                        "display": "background",
                        "backgroundColor": "rgba(40, 167, 69)"
                    })
                
                # 3. Obtener Ausencias como eventos de fondo rojos
                sql_ausencias = f"SELECT empleado_id, fecha_hora_inicio, fecha_hora_fin FROM ausencias_empleado WHERE empleado_id IN ({placeholders}) AND aprobado = TRUE AND DATE(fecha_hora_inicio) <= %s AND DATE(fecha_hora_fin) >= %s"
                cursor.execute(sql_ausencias, tuple(recursos_ids) + (fecha_str, fecha_str))
                for ausencia in cursor.fetchall():
                    eventos.append({ "resourceId": ausencia['empleado_id'], "start": ausencia['fecha_hora_inicio'].isoformat(), "end": ausencia['fecha_hora_fin'].isoformat(), "display": "background", "backgroundColor": "rgba(220, 53, 69, 0.4)" })
                
                # 4. Obtener Reservas como eventos normales
                sql_reservas = f"SELECT r.id, r.fecha_hora_inicio as start, r.fecha_hora_fin as end, r.estado, r.empleado_id as resourceId, CONCAT(s.nombre, ' - ', c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) as title FROM reservas r JOIN servicios s ON r.servicio_id = s.id LEFT JOIN clientes c ON r.cliente_id = c.id WHERE r.sucursal_id = %s AND DATE(r.fecha_hora_inicio) = %s AND r.estado NOT IN ('Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio')"
                cursor.execute(sql_reservas, (sucursal_id, fecha_str))
                for reserva in cursor.fetchall():
                    reserva['start'] = reserva['start'].isoformat()
                    reserva['end'] = reserva['end'].isoformat()
                    reserva['borderColor'] = '#b49b4c'
                    reserva['backgroundColor'] = '#D4AF37' if reserva['estado'] != 'Completada' else '#198754'
                    eventos.append(reserva)

    except Exception as e:
        current_app.logger.error(f"Error fatal en api_agenda_dia_data: {e}", exc_info=True)
        return jsonify({"error": "Error interno del servidor al procesar la solicitud."}), 500

    return jsonify({"recursos": recursos, "eventos": eventos})

    
def timedelta_to_time_obj(td):
    if td is None: return None
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return time(hours, minutes)


@main_bp.route('/reservas/nueva', methods=['POST'])
@login_required
def nueva_reserva():
    """
    Procesa la creación de una nueva reserva desde una petición AJAX (JSON).
    Versión final y corregida.
    """
    if not request.is_json:
        return jsonify({"success": False, "message": "Error: Se esperaba contenido JSON."}), 400
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Error: No se recibieron datos."}), 400

    db_conn = get_db()
    
    try:
        # --- 1. Recoger y Validar Datos del Payload JSON (FORMA CORREGIDA) ---
        errores = []
        
        sucursal_id = int(data.get('sucursal_id')) if data.get('sucursal_id') else None
        cliente_id = int(data.get('cliente_id')) if data.get('cliente_id') else None
        empleado_id = int(data.get('empleado_id')) if data.get('empleado_id') else None
        servicio_id = int(data.get('servicio_id')) if data.get('servicio_id') else None
        fecha_hora_inicio_str = data.get('fecha_hora_inicio')
        notas_cliente = data.get('notas_cliente', '').strip() or None

        if not sucursal_id: errores.append("La sucursal es requerida.")
        if not cliente_id or cliente_id == 0: errores.append("Debe seleccionar un cliente.")
        if not empleado_id: errores.append("Colaborador es obligatorio.")
        if not servicio_id: errores.append("Debe seleccionar un servicio.")
        
        if not fecha_hora_inicio_str:
            errores.append('Falta la fecha y hora de inicio.')
        else:
            try:
                fecha_hora_inicio = datetime.fromisoformat(fecha_hora_inicio_str)
                if fecha_hora_inicio < datetime.now():
                    errores.append('La fecha y hora de inicio no puede ser en el pasado.')
            except ValueError:
                errores.append('Formato de fecha y hora de inicio inválido.')

        if errores:
            return jsonify({"success": False, "errors": errores}), 400

        # --- 2. Calcular fecha_hora_fin y Validar Disponibilidad ---
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT duracion_minutos, precio FROM servicios WHERE id = %s AND activo = TRUE", (servicio_id,))
            servicio_seleccionado = cursor.fetchone()
            if not servicio_seleccionado:
                return jsonify({"success": False, "message": "Servicio seleccionado no válido o inactivo."}), 400
            
            duracion_servicio = timedelta(minutes=servicio_seleccionado['duracion_minutos'])
            fecha_hora_fin = fecha_hora_inicio + duracion_servicio
            precio_del_servicio = servicio_seleccionado['precio']

            # Validar disponibilidad (horarios, ausencias, otras reservas)
            dia_semana_reserva = fecha_hora_inicio.isoweekday()
            cursor.execute("SELECT hora_inicio, hora_fin FROM horarios_empleado WHERE empleado_id = %s AND dia_semana = %s", (empleado_id, dia_semana_reserva))
            turnos_del_dia = cursor.fetchall()
            if not turnos_del_dia:
                return jsonify({"success": False, "message": f"El colaborador no trabaja el día seleccionado."}), 409
            
            esta_en_turno_valido = False
            for turno in turnos_del_dia:
                turno_inicio_time_obj = timedelta_to_time_obj(turno['hora_inicio'])
                turno_fin_time_obj = timedelta_to_time_obj(turno['hora_fin'])
                if fecha_hora_inicio.time() >= turno_inicio_time_obj and fecha_hora_fin.time() <= turno_fin_time_obj:
                    esta_en_turno_valido = True
                    break
            if not esta_en_turno_valido:
                return jsonify({"success": False, "message": "La hora de la reserva está fuera del horario laboral del colaborador."}), 409

            cursor.execute("SELECT id FROM ausencias_empleado WHERE empleado_id = %s AND aprobado = TRUE AND fecha_hora_inicio < %s AND fecha_hora_fin > %s", (empleado_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone():
                return jsonify({"success": False, "message": "El colaborador tiene una ausencia registrada en este horario."}), 409

            cursor.execute("SELECT id FROM reservas WHERE empleado_id = %s AND sucursal_id = %s AND estado NOT IN ('Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio', 'Completada') AND fecha_hora_inicio < %s AND fecha_hora_fin > %s", (empleado_id, sucursal_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone():
                return jsonify({"success": False, "message": "El colaborador ya tiene otra reserva en el horario seleccionado."}), 409
            
            # --- 3. Si todo es válido, guardar en la BD ---
            sql = "INSERT INTO reservas (sucursal_id, cliente_id, empleado_id, servicio_id, fecha_hora_inicio, fecha_hora_fin, estado, notas_cliente, precio_cobrado) VALUES (%s, %s, %s, %s, %s, %s, 'Programada', %s, %s)"
            val = (sucursal_id, cliente_id, empleado_id, servicio_id, fecha_hora_inicio, fecha_hora_fin, notas_cliente, precio_del_servicio)
            
            cursor.execute(sql, val)
            db_conn.commit()
            
            return jsonify({"success": True, "message": f'Reserva creada exitosamente para el {fecha_hora_inicio.strftime("%d/%m/%Y a las %H:%M")}.'}), 201

    except (ValueError, mysql.connector.Error, Exception) as e:
        if db_conn and db_conn.in_transaction: db_conn.rollback()
        current_app.logger.error(f"Error procesando nueva reserva: {e}")
        return jsonify({"success": False, "message": f"No se pudo guardar la reserva. Error: {str(e)}"}), 500
    
@main_bp.route('/reservas/editar/<int:reserva_id>', methods=['POST'])
@login_required
def editar_reserva(reserva_id):
    """
    Procesa la edición de una reserva existente desde una petición AJAX (JSON).
    """
    if not request.is_json:
        return jsonify({"success": False, "message": "Error: Se esperaba contenido JSON."}), 400
    
    data = request.get_json()
    db = get_db()

    try:
        # 1. Recoger y validar datos del formulario
        cliente_id = int(data.get('cliente_id')) if data.get('cliente_id') else None
        empleado_id = int(data.get('empleado_id')) if data.get('empleado_id') else None
        servicio_id = int(data.get('servicio_id')) if data.get('servicio_id') else None
        fecha_hora_inicio_str = data.get('fecha_hora_inicio')
        precio_cobrado_str = data.get('precio_cobrado')
        notas_cliente = data.get('notas_cliente', '').strip() or None
        notas_internas = data.get('notas_internas', '').strip() or None

        errores = []
        if not all([cliente_id, empleado_id, servicio_id, fecha_hora_inicio_str]):
            errores.append("Cliente, Colaborador, Servicio y Fecha de Inicio son obligatorios.")
        
        try:
            fecha_hora_inicio = datetime.fromisoformat(fecha_hora_inicio_str)
        except (ValueError, TypeError):
            errores.append("El formato de la fecha de inicio es inválido.")
        
        if errores:
            return jsonify({"success": False, "errors": errores}), 400

        with db.cursor(dictionary=True) as cursor:
            # 2. Calcular nueva fecha de fin y realizar validaciones de disponibilidad
            cursor.execute("SELECT duracion_minutos, precio FROM servicios WHERE id = %s", (servicio_id,))
            servicio_info = cursor.fetchone()
            if not servicio_info:
                return jsonify({"success": False, "message": "El servicio seleccionado no es válido."}), 400

            duracion = timedelta(minutes=servicio_info['duracion_minutos'])
            nueva_fecha_fin = fecha_hora_inicio + duracion
            
            # Validar que la nueva hora esté dentro del horario laboral
            dia_semana_reserva = fecha_hora_inicio.isoweekday()
            cursor.execute("SELECT hora_inicio, hora_fin FROM horarios_empleado WHERE empleado_id = %s AND dia_semana = %s", (empleado_id, dia_semana_reserva))
            turnos_del_dia = cursor.fetchall()
            if not turnos_del_dia:
                return jsonify({"success": False, "message": f"El colaborador no trabaja el día seleccionado."}), 409

            esta_en_turno = False
            for turno in turnos_del_dia:
                inicio_turno = timedelta_to_time_obj(turno['hora_inicio'])
                fin_turno = timedelta_to_time_obj(turno['hora_fin'])
                if fecha_hora_inicio.time() >= inicio_turno and nueva_fecha_fin.time() <= fin_turno:
                    esta_en_turno = True
                    break
            if not esta_en_turno:
                 return jsonify({"success": False, "message": "El nuevo horario está fuera del turno laboral del colaborador."}), 409

            # Validar que no choque con otra reserva (excluyendo la reserva actual)
            cursor.execute("""
                SELECT id FROM reservas 
                WHERE empleado_id = %s AND id != %s AND estado NOT IN ('Cancelada', 'No Asistio', 'Cancelada por Staff') 
                AND fecha_hora_inicio < %s AND fecha_hora_fin > %s
            """, (empleado_id, reserva_id, nueva_fecha_fin, fecha_hora_inicio))
            if cursor.fetchone():
                return jsonify({"success": False, "message": "El nuevo horario entra en conflicto con otra reserva existente."}), 409

            # Validar que no choque con una ausencia
            cursor.execute("SELECT id FROM ausencias_empleado WHERE empleado_id = %s AND aprobado = TRUE AND fecha_hora_inicio < %s AND fecha_hora_fin > %s", (empleado_id, nueva_fecha_fin, fecha_hora_inicio))
            if cursor.fetchone():
                 return jsonify({"success": False, "message": "El nuevo horario coincide con una ausencia registrada."}), 409

            # 3. Si todas las validaciones pasan, actualizar la reserva
            sql_update = """UPDATE reservas SET 
                                cliente_id = %s, empleado_id = %s, servicio_id = %s, 
                                fecha_hora_inicio = %s, fecha_hora_fin = %s, 
                                precio_cobrado = %s, notas_cliente = %s, notas_internas = %s
                            WHERE id = %s"""
            
            precio_final = float(precio_cobrado_str) if precio_cobrado_str else servicio_info['precio']
            
            val_update = (
                cliente_id, empleado_id, servicio_id,
                fecha_hora_inicio, nueva_fecha_fin,
                precio_final, notas_cliente, notas_internas,
                reserva_id
            )
            cursor.execute(sql_update, val_update)
            db.commit()

        return jsonify({"success": True, "message": "Reserva actualizada correctamente."})

    except Exception as e:
        get_db().rollback()
        current_app.logger.error(f"Error editando reserva: {e}")
        return jsonify({"success": False, "message": f"Error interno al guardar los cambios: {str(e)}"}), 500

@main_bp.route('/reservas/cancelar/<int:reserva_id>', methods=['POST'])
@login_required
def cancelar_reserva(reserva_id):
    """
    Actualiza el estado de una reserva a 'Cancelada por Staff'.
    """
    db = get_db()
    try:
        with db.cursor() as cursor:
            # Buscamos la reserva para asegurarnos de que existe y no está ya en un estado final
            cursor.execute("SELECT id, estado FROM reservas WHERE id = %s", (reserva_id,))
            reserva = cursor.fetchone()

            if not reserva:
                return jsonify({"success": False, "message": "La reserva no fue encontrada."}), 404
            
            # Estados que consideramos finales y que no se pueden cancelar de nuevo
            estados_finales = ['Completada', 'Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio']
            if reserva[1] in estados_finales:
                return jsonify({"success": False, "message": f"No se puede cancelar una reserva que ya está '{reserva[1]}'."}), 409 # 409 = Conflicto

            # Actualizamos el estado
            cursor.execute("UPDATE reservas SET estado = 'Cancelada por Staff' WHERE id = %s", (reserva_id,))
            db.commit()
            
            return jsonify({"success": True, "message": "La reserva ha sido cancelada exitosamente."})

    except mysql.connector.Error as err:
        db.rollback()
        current_app.logger.error(f"Error al cancelar reserva: {err}")
        return jsonify({"success": False, "message": "Error de base de datos al intentar cancelar la reserva."}), 500

@main_bp.route('/api/reservas/<int:reserva_id>/completar', methods=['POST'])
@login_required
def completar_reserva(reserva_id):
    """
    Actualiza el estado de una reserva a 'Completada' y devuelve una URL
    para redirigir al formulario de venta.
    """
    db = get_db()
    try:
        with db.cursor(dictionary=True) as cursor:
            # (Aquí puedes añadir validaciones si lo deseas)
            cursor.execute("UPDATE reservas SET estado = 'Completada' WHERE id = %s", (reserva_id,))
            db.commit()
            
            # Crear la URL de redirección
            url_venta = url_for('main.nueva_venta', reserva_id=reserva_id)
            return jsonify({
                "success": True, 
                "message": "Reserva marcada como completada. Redirigiendo a la venta...",
                "redirect_url": url_venta
            })

    except mysql.connector.Error as err:
        db.rollback()
        return jsonify({"success": False, "message": f"Error de base de datos: {err}"}), 500

@main_bp.route('/reservas/reagendar', methods=['POST'])
@login_required
@admin_required
def reagendar_reserva():
    """
    Valida y actualiza una reserva movida o redimensionada.
    Versión final con manejo completo de zonas horarias.
    """
    data = request.get_json()
    reserva_id = data.get('reserva_id')
    nuevo_inicio_str = data.get('nuevo_inicio')
    nuevo_fin_str = data.get('nuevo_fin')
    nuevo_colaborador_id = data.get('nuevo_colaborador_id')

    if not all([reserva_id, nuevo_inicio_str, nuevo_colaborador_id]):
        return jsonify({"success": False, "message": "Faltan datos para reagendar."}), 400

    db = get_db()
    try:
        with db.cursor(dictionary=True) as cursor:
            # --- CORRECCIÓN DEFINITIVA DE ZONA HORARIA ---
            # 1. Definir la zona horaria de Perú (UTC-5)
            peru_tz = timezone(timedelta(hours=-5))

            # 2. Convertir la fecha UTC que viene de JavaScript a un objeto datetime "consciente"
            fecha_hora_inicio_aware = datetime.fromisoformat(nuevo_inicio_str.replace('Z', '+00:00')).astimezone(peru_tz)
            
            # 3. Convertir la fecha a "ingenua" (naive) para que sea compatible con la base de datos
            fecha_hora_inicio = fecha_hora_inicio_aware.replace(tzinfo=None)

            if nuevo_fin_str:
                fecha_hora_fin_aware = datetime.fromisoformat(nuevo_fin_str.replace('Z', '+00:00')).astimezone(peru_tz)
                fecha_hora_fin = fecha_hora_fin_aware.replace(tzinfo=None)
            else:
                cursor.execute("SELECT s.duracion_minutos FROM servicios s JOIN reservas r ON s.id = r.servicio_id WHERE r.id = %s", (reserva_id,))
                servicio_info = cursor.fetchone()
                if not servicio_info:
                    return jsonify({"success": False, "message": "Servicio de la reserva no encontrado."}), 404
                duracion = timedelta(minutes=servicio_info['duracion_minutos'])
                fecha_hora_fin = fecha_hora_inicio + duracion
            
            # 4. Validar que la nueva hora no sea en el pasado
            if fecha_hora_inicio < datetime.now():
                return jsonify({"success": False, "message": "No se puede mover una reserva a una fecha u hora pasada."}), 409

            # 5. Realizar todas las validaciones comparando fechas "ingenuas"
            dia_semana_reserva = fecha_hora_inicio.isoweekday()
            cursor.execute("SELECT hora_inicio, hora_fin FROM horarios_empleado WHERE empleado_id = %s AND dia_semana = %s", (nuevo_colaborador_id, dia_semana_reserva))
            turnos_del_dia = cursor.fetchall()
            if not turnos_del_dia:
                return jsonify({"success": False, "message": "El colaborador no trabaja en el día seleccionado."}), 409

            esta_en_turno = False
            for turno in turnos_del_dia:
                inicio_turno = timedelta_to_time_obj(turno['hora_inicio'])
                fin_turno = timedelta_to_time_obj(turno['hora_fin'])
                if fecha_hora_inicio.time() >= inicio_turno and fecha_hora_fin.time() <= fin_turno:
                    esta_en_turno = True
                    break
            if not esta_en_turno:
                 return jsonify({"success": False, "message": "El nuevo horario (inicio o fin) está fuera del turno laboral del colaborador."}), 409

            cursor.execute("SELECT id FROM reservas WHERE empleado_id = %s AND id != %s AND estado NOT IN ('Cancelada', 'No Asistio', 'Cancelada por Staff') AND fecha_hora_inicio < %s AND fecha_hora_fin > %s", (nuevo_colaborador_id, reserva_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone():
                return jsonify({"success": False, "message": "El nuevo horario entra en conflicto con otra reserva existente."}), 409

            cursor.execute("SELECT id FROM ausencias_empleado WHERE empleado_id = %s AND aprobado = TRUE AND fecha_hora_inicio < %s AND fecha_hora_fin > %s", (nuevo_colaborador_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone():
                 return jsonify({"success": False, "message": "El nuevo horario coincide con un receso u otra ausencia registrada."}), 409

            # 6. Si todo es válido, actualizar la reserva
            sql_update = "UPDATE reservas SET fecha_hora_inicio = %s, fecha_hora_fin = %s, empleado_id = %s WHERE id = %s"
            cursor.execute(sql_update, (fecha_hora_inicio, fecha_hora_fin, nuevo_colaborador_id, reserva_id))
            db.commit()

        return jsonify({"success": True, "message": "Reserva reagendada exitosamente."})

    except Exception as e:
        if db.in_transaction:
            db.rollback()
        current_app.logger.error(f"Error reagendando reserva: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error interno del servidor: {str(e)}"}), 500

@main_bp.route('/api/reservas/<int:reserva_id>/completar', methods=['POST'])
@login_required
def api_marcar_reserva_completada(reserva_id):
    """
    Marca una reserva específica como 'Completada'.
    """
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        # Verificar si la reserva existe y no está ya en un estado final que impida completarla
        cursor.execute("SELECT id, estado FROM reservas WHERE id = %s", (reserva_id,))
        reserva = cursor.fetchone()

        if not reserva:
            return jsonify({"success": False, "message": "Reserva no encontrada."}), 404

        # Estados que impedirían marcar como completada (ya está completada o cancelada)
        estados_no_modificables = ['Completada', 'Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio']
        if reserva['estado'] in estados_no_modificables:
            return jsonify({"success": False, "message": f"La reserva ya está en estado '{reserva['estado']}' y no se puede marcar como completada."}), 409 # 409 Conflict

        nuevo_estado = "Completada"
        cursor_update = db_conn.cursor()
        cursor_update.execute("UPDATE reservas SET estado = %s WHERE id = %s", (nuevo_estado, reserva_id))
        db_conn.commit()
        
        return jsonify({"success": True, "message": f"Reserva #{reserva_id} marcada como 'Completada' exitosamente."}), 200

    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        current_app.logger.error(f"Error DB en api_marcar_reserva_completada (Reserva ID: {reserva_id}): {err}")
        return jsonify({"success": False, "message": "Error interno del servidor al actualizar la reserva.", "detalle": str(err)}), 500
    finally:
        if cursor:
            cursor.close()
        if 'cursor_update' in locals() and cursor_update:
            cursor_update.close()

@main_bp.route('/api/reservas/<int:reserva_id>', methods=['GET'])
@login_required
def api_get_reserva_detalle(reserva_id):
    """
    Devuelve los detalles de una reserva específica en formato JSON.
    """
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        sql = """
            SELECT 
                r.id, 
                r.fecha_hora_inicio, 
                r.fecha_hora_fin, 
                r.estado,
                r.notas_cliente,
                r.notas_internas,
                r.precio_cobrado,
                r.cliente_id,
                CONCAT(c.nombres, ' ', c.apellidos) AS cliente_nombre_completo,
                r.empleado_id,
                CONCAT(e.nombres, ' ', e.apellidos) AS empleado_nombre_completo,
                r.servicio_id,
                s.nombre AS servicio_nombre,
                s.duracion_minutos AS servicio_duracion_minutos,
                s.precio AS servicio_precio_base,
                r.fecha_creacion,
                r.fecha_actualizacion
            FROM reservas r
            JOIN clientes c ON r.cliente_id = c.id
            JOIN empleados e ON r.empleado_id = e.id
            JOIN servicios s ON r.servicio_id = s.id
            WHERE r.id = %s
        """
        cursor.execute(sql, (reserva_id,))
        reserva = cursor.fetchone()

        if reserva:
            # Convertir objetos datetime a strings ISO para JSON
            if reserva.get('fecha_hora_inicio'):
                reserva['fecha_hora_inicio'] = reserva['fecha_hora_inicio'].isoformat()
            if reserva.get('fecha_hora_fin'):
                reserva['fecha_hora_fin'] = reserva['fecha_hora_fin'].isoformat()
            if reserva.get('fecha_creacion'):
                reserva['fecha_creacion'] = reserva['fecha_creacion'].isoformat()
            if reserva.get('fecha_actualizacion'):
                reserva['fecha_actualizacion'] = reserva['fecha_actualizacion'].isoformat()
            return jsonify(reserva), 200
        else:
            return jsonify({"error": "Reserva no encontrada"}), 404

    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_get_reserva_detalle (Reserva ID: {reserva_id}): {err}")
        return jsonify({"error": "Error interno del servidor al obtener detalles de la reserva.", "detalle": str(err)}), 500
    finally:
        if cursor:
            cursor.close()



# --- RUTAS PARA HORARIOS DE EMPLEADOS ---

def obtener_dias_semana():
    # ... (esta función ya la tienes) ...
    dias = OrderedDict()
    dias[1] = "Lunes"
    dias[2] = "Martes"
    dias[3] = "Miércoles"
    dias[4] = "Jueves"
    dias[5] = "Viernes"
    dias[6] = "Sábado"
    dias[7] = "Domingo"
    return dias

def generar_opciones_tiempo_15min():
    """
    Genera una lista de strings de tiempo en formato HH:MM cada 15 minutos.
    """
    opciones = []
    hora_actual = time(0, 0) # Empezar a las 00:00
    fin_dia = time(23, 59)   # Límite
    intervalo = timedelta(minutes=15)
    
    while hora_actual <= fin_dia:
        opciones.append(hora_actual.strftime('%H:%M'))
        # Incrementar la hora actual. Necesitamos un datetime para sumar timedelta.
        # Convertimos time a datetime, sumamos, y luego volvemos a time.
        dt_temp = datetime.combine(datetime.today(), hora_actual) + intervalo
        hora_actual = dt_temp.time()
        # Evitar un bucle infinito si algo sale mal con el incremento (poco probable aquí)
        if len(opciones) > (24 * 4): break 
    return opciones

def timedelta_to_time(td):
    if td is None: return None
    # Un timedelta de MySQL para un campo TIME representa la duración desde 00:00:00
    # total_seconds() nos da esa duración en segundos.
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    # Los segundos los ignoramos para la conversión a HH:MM, o puedes incluirlos si es time(hours, minutes, seconds)
    return time(hours, minutes) 


@main_bp.route('/empleados/<int:empleado_id>/horarios', methods=['GET'])
@login_required
@admin_required
def gestionar_horarios_empleado(empleado_id):
    db_conn = get_db()
    cursor_empleado = None
    cursor_horarios = None
    empleado = None # Inicializar
    horarios_por_dia = {dia_num: [] for dia_num in range(1, 8)} # Inicializar

    try:
        cursor_empleado = db_conn.cursor(dictionary=True)
        cursor_empleado.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_empleado.fetchone()

        if not empleado:
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        cursor_horarios = db_conn.cursor(dictionary=True)
        cursor_horarios.execute("""
            SELECT id, dia_semana, TIME_FORMAT(hora_inicio, '%H:%i') AS hora_inicio_f, TIME_FORMAT(hora_fin, '%H:%i') AS hora_fin_f 
            FROM horarios_empleado 
            WHERE empleado_id = %s 
            ORDER BY dia_semana, hora_inicio
        """, (empleado_id,))
        horarios_existentes_raw = cursor_horarios.fetchall()
        
        for horario in horarios_existentes_raw:
            horarios_por_dia[horario['dia_semana']].append(horario)

    except mysql.connector.Error as err:
        flash(f"Error al cargar datos de horarios: {err}", "danger")
        current_app.logger.error(f"Error DB en gestionar_horarios_empleado (Empleado ID: {empleado_id}): {err}")
        # empleado se quedará como None si falla aquí, o horarios_por_dia vacío
    finally:
        if cursor_empleado: cursor_empleado.close()
        if cursor_horarios: cursor_horarios.close()

    if not empleado: 
        return redirect(url_for('main.listar_empleados'))
        
    dias_semana_map = obtener_dias_semana()
    opciones_tiempo = generar_opciones_tiempo_15min() # Generar opciones de tiempo
    
    return render_template('empleados/gestionar_horarios.html', 
                           empleado=empleado, 
                           horarios_por_dia=horarios_por_dia, 
                           dias_semana_map=dias_semana_map,
                           opciones_tiempo=opciones_tiempo) # Pasar opciones a la plantilla

@main_bp.route('/empleados/<int:empleado_id>/horarios/agregar_turno', methods=['POST'])
@login_required
@admin_required
def agregar_turno_horario(empleado_id):
    db_conn = get_db() # Mover get_db() al inicio para usarlo en varias partes si es necesario
    cursor_check_empleado = None # Inicializar
    
    # Validar que el empleado exista (opcional, pero bueno)
    try:
        cursor_check_empleado = db_conn.cursor(dictionary=True) # Usar dictionary=True para acceder por nombre
        cursor_check_empleado.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cursor_check_empleado.fetchone():
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))
    except mysql.connector.Error as err_check:
        flash(f"Error al verificar empleado: {err_check}", "danger")
        return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id))
    finally:
        if cursor_check_empleado: cursor_check_empleado.close()

    dia_semana = request.form.get('dia_semana', type=int)
    hora_inicio_str = request.form.get('hora_inicio') # Ej: "09:00"
    hora_fin_str = request.form.get('hora_fin')     # Ej: "13:00"

    errores = []
    if not dia_semana or dia_semana not in range(1, 8):
        errores.append("Día de la semana inválido.")
    if not hora_inicio_str:
        errores.append("La hora de inicio es obligatoria.")
    if not hora_fin_str:
        errores.append("La hora de fin es obligatoria.")
    
    h_inicio_nueva = None
    h_fin_nueva = None

    if not errores: # Solo intentar convertir horas si los strings no están vacíos
        try:
            h_inicio_nueva = datetime.strptime(hora_inicio_str, '%H:%M').time()
            h_fin_nueva = datetime.strptime(hora_fin_str, '%H:%M').time()
            if h_fin_nueva <= h_inicio_nueva:
                errores.append("La hora de fin debe ser posterior a la hora de inicio.")
        except ValueError:
            errores.append("Formato de hora inválido. Use HH:MM (ej. 09:00, 14:30).")

    # --- INICIO DE VALIDACIÓN DE SOLAPAMIENTO (AJUSTADA) ---
    if not errores: # Solo verificar solapamiento si las validaciones anteriores pasaron
        cursor_solapamiento = None
        try:
            cursor_solapamiento = db_conn.cursor(dictionary=True) # dictionary=True para acceder por nombre
            # Obtener todos los turnos existentes para ese empleado y día
            # La BD devuelve objetos timedelta para campos TIME
            cursor_solapamiento.execute("""
                SELECT hora_inicio, hora_fin 
                FROM horarios_empleado 
                WHERE empleado_id = %s AND dia_semana = %s
            """, (empleado_id, dia_semana))
            turnos_existentes_raw = cursor_solapamiento.fetchall()

            # Convertir timedelta (de la BD) a datetime.time para comparación
            def timedelta_to_time(td):
                if td is None: return None
                total_seconds = int(td.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                return time(hours, minutes)

            for turno_raw in turnos_existentes_raw:
                h_inicio_existente = timedelta_to_time(turno_raw['hora_inicio'])
                h_fin_existente = timedelta_to_time(turno_raw['hora_fin'])
                
                if h_inicio_existente is None or h_fin_existente is None: # Seguridad
                    continue

                # Comprobar solapamiento:
                if (h_inicio_nueva < h_fin_existente) and (h_fin_nueva > h_inicio_existente):
                    errores.append(f"El nuevo turno ({hora_inicio_str} - {hora_fin_str}) se solapa con un turno existente ({h_inicio_existente.strftime('%H:%M')} - {h_fin_existente.strftime('%H:%M')}).")
                    break 
        except mysql.connector.Error as err_solap:
            current_app.logger.error(f"Error DB verificando solapamiento: {err_solap}")
            errores.append("Error al verificar solapamiento de turnos.")
        finally:
            if cursor_solapamiento: cursor_solapamiento.close()
    # --- FIN DE VALIDACIÓN DE SOLAPAMIENTO (AJUSTADA) ---

    if errores:
        for error in errores:
            flash(error, 'warning')
    else:
        # Si no hay errores, proceder con la inserción
        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            sql = "INSERT INTO horarios_empleado (empleado_id, dia_semana, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s)"
            # Guardar como string 'HH:MM:SS' o 'HH:MM' que MySQL TIME acepta
            cursor_insert.execute(sql, (empleado_id, dia_semana, hora_inicio_str + ':00', hora_fin_str + ':00'))
            db_conn.commit()
            flash("Nuevo turno agregado exitosamente.", "success")
        except mysql.connector.Error as err:
            db_conn.rollback()
            flash(f"Error al agregar el turno: {err}", "danger")
            current_app.logger.error(f"Error DB en agregar_turno_horario (Empleado ID: {empleado_id}): {err}")
        finally:
            if cursor_insert: cursor_insert.close()

    return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id))

@main_bp.route('/horarios_empleado/eliminar/<int:horario_id>', methods=['GET']) # Usamos GET por simplicidad con confirmación JS
@login_required
@admin_required
def eliminar_turno_horario(horario_id):
    """
    Elimina un turno específico de la tabla horarios_empleado.
    """
    empleado_id_para_redirect = None
    db_conn = get_db()
    cursor_find = None
    cursor_delete = None

    try:
        # Primero, encontrar el empleado_id asociado con este horario_id para poder redirigir correctamente
        cursor_find = db_conn.cursor(dictionary=True)
        cursor_find.execute("SELECT empleado_id FROM horarios_empleado WHERE id = %s", (horario_id,))
        horario_info = cursor_find.fetchone()

        if not horario_info:
            flash(f"Turno con ID {horario_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados')) # Redirigir a la lista general de empleados si no se sabe a dónde más
        
        empleado_id_para_redirect = horario_info['empleado_id']

        # Proceder a eliminar el turno
        cursor_delete = db_conn.cursor()
        cursor_delete.execute("DELETE FROM horarios_empleado WHERE id = %s", (horario_id,))
        db_conn.commit()

        if cursor_delete.rowcount > 0:
            flash("Turno eliminado exitosamente.", "success")
        else:
            # Esto no debería ocurrir si el find anterior tuvo éxito, pero por si acaso.
            flash(f"No se pudo eliminar el turno con ID {horario_id}.", "warning")

    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f"Error al eliminar el turno: {err}", "danger")
        current_app.logger.error(f"Error DB en eliminar_turno_horario (Horario ID: {horario_id}): {err}")
        # Si tenemos empleado_id_para_redirect, intentamos redirigir ahí, sino a la lista de empleados
        if empleado_id_para_redirect:
            return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id_para_redirect))
        else:
            return redirect(url_for('main.listar_empleados'))
    finally:
        if cursor_find:
            cursor_find.close()
        if cursor_delete:
            cursor_delete.close()
    
    # Si todo fue bien y tenemos el empleado_id_para_redirect
    if empleado_id_para_redirect:
        return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id_para_redirect))
    else:
        # Fallback por si algo muy raro pasa y no tenemos el ID del empleado
        return redirect(url_for('main.listar_empleados'))

@main_bp.route('/horarios_empleado/editar/<int:horario_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_turno_horario(horario_id):
    db_conn = get_db()
    cursor = None # Para usar en finally

    # Obtener el turno actual para editar y su empleado_id
    turno_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM horarios_empleado WHERE id = %s", (horario_id,))
        turno_actual = cursor.fetchone()
        if turno_actual:
            # Convertir TIME de BD (timedelta) a objetos time de Python para el formulario
            turno_actual['hora_inicio_obj'] = timedelta_to_time(turno_actual['hora_inicio'])
            turno_actual['hora_fin_obj'] = timedelta_to_time(turno_actual['hora_fin'])
    except mysql.connector.Error as err:
        flash(f"Error al buscar el turno: {err}", "danger")
        current_app.logger.error(f"Error DB buscando turno en editar_turno_horario (ID: {horario_id}): {err}")
        return redirect(request.referrer or url_for('main.listar_empleados')) # Volver a la página anterior o a lista empleados
    finally:
        if cursor: cursor.close()

    if not turno_actual:
        flash(f"Turno con ID {horario_id} no encontrado.", "warning")
        return redirect(url_for('main.listar_empleados')) # O alguna otra página por defecto

    empleado_id = turno_actual['empleado_id']

    # Obtener info del empleado para el título y contexto
    empleado = None
    cursor_emp = None
    try:
        cursor_emp = db_conn.cursor(dictionary=True)
        # CORRECCIÓN AQUÍ: Añadir 'id' a la consulta SELECT
        cursor_emp.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_emp.fetchone()
    except mysql.connector.Error as err_emp:
        flash(f"Error al cargar datos del empleado: {err_emp}", "danger")
        current_app.logger.error(f"Error DB cargando empleado en editar_turno_horario: {err_emp}") # Log del error
    finally:
        if cursor_emp: cursor_emp.close()
    
    if not empleado: 
        flash("Empleado asociado al turno no encontrado. No se puede editar el turno.", "danger")
        return redirect(url_for('main.listar_empleados')) # Redirigir si el empleado no existe
    
    opciones_tiempo = generar_opciones_tiempo_15min() # Función que ya creamos
    dias_semana_map = obtener_dias_semana() # Función que ya creamos

    if request.method == 'POST':
        dia_semana_nuevo_str = request.form.get('dia_semana') # Puede o no ser editable
        hora_inicio_nueva_str = request.form.get('hora_inicio')
        hora_fin_nueva_str = request.form.get('hora_fin')

        errores = []
        dia_semana_nuevo = None
        h_inicio_nueva = None
        h_fin_nueva = None

        try:
            dia_semana_nuevo = int(dia_semana_nuevo_str)
            if dia_semana_nuevo not in range(1, 8):
                errores.append("Día de la semana inválido.")
        except (ValueError, TypeError):
            errores.append("Día de la semana debe ser un número.")

        if not hora_inicio_nueva_str: errores.append("La hora de inicio es obligatoria.")
        if not hora_fin_nueva_str: errores.append("La hora de fin es obligatoria.")

        if not errores: # Solo convertir si no hay errores previos
            try:
                h_inicio_nueva = datetime.strptime(hora_inicio_nueva_str, '%H:%M').time()
                h_fin_nueva = datetime.strptime(hora_fin_nueva_str, '%H:%M').time()
                if h_fin_nueva <= h_inicio_nueva:
                    errores.append("La hora de fin debe ser posterior a la hora de inicio.")
            except ValueError:
                errores.append("Formato de hora inválido. Use HH:MM.")
        
        # Validación de solapamiento (excluyendo el turno actual que se está editando)
        if not errores:
            cursor_solap = None
            try:
                cursor_solap = db_conn.cursor(dictionary=True)
                cursor_solap.execute("""
                    SELECT hora_inicio, hora_fin FROM horarios_empleado 
                    WHERE empleado_id = %s AND dia_semana = %s AND id != %s
                """, (empleado_id, dia_semana_nuevo, horario_id)) # id != horario_id
                turnos_existentes_raw = cursor_solap.fetchall()

                for turno_raw in turnos_existentes_raw:
                    h_inicio_existente = timedelta_to_time(turno_raw['hora_inicio'])
                    h_fin_existente = timedelta_to_time(turno_raw['hora_fin'])
                    if h_inicio_existente and h_fin_existente and \
                       (h_inicio_nueva < h_fin_existente) and (h_fin_nueva > h_inicio_existente):
                        errores.append(f"El horario modificado ({hora_inicio_nueva_str}-{hora_fin_nueva_str}) se solapa con otro turno existente.")
                        break
            except mysql.connector.Error as err_sol:
                current_app.logger.error(f"Error DB verificando solapamiento en edición: {err_sol}")
                errores.append("Error al verificar solapamiento de turnos.")
            finally:
                if cursor_solap: cursor_solap.close()

        if errores:
            for error in errores:
                flash(error, 'warning')
            # Volver a renderizar el formulario de edición con los errores y datos
            return render_template('empleados/form_editar_turno.html',
                                   turno_actual=turno_actual, # Datos originales del turno
                                   empleado=empleado,
                                   opciones_tiempo=opciones_tiempo,
                                   dias_semana_map=dias_semana_map,
                                   form_data=request.form, # Datos que el usuario intentó enviar
                                   horario_id=horario_id)
        else:
            # Actualizar el turno en la BD
            cursor_upd = None
            try:
                cursor_upd = db_conn.cursor()
                sql_update = """UPDATE horarios_empleado SET 
                                    dia_semana = %s, hora_inicio = %s, hora_fin = %s 
                                WHERE id = %s"""
                # Guardar como string HH:MM:SS
                cursor_upd.execute(sql_update, (dia_semana_nuevo, hora_inicio_nueva_str + ':00', hora_fin_nueva_str + ':00', horario_id))
                db_conn.commit()
                flash("Turno actualizado exitosamente.", "success")
                return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                flash(f"Error al actualizar el turno: {err_upd}", "danger")
                current_app.logger.error(f"Error DB en POST editar_turno_horario (ID: {horario_id}): {err_upd}")
            finally:
                if cursor_upd: cursor_upd.close()
        
        # Si llega aquí después de un error de BD en el update, re-renderizar el form
        return render_template('empleados/form_editar_turno.html',
                               turno_actual=turno_actual,
                               empleado=empleado,
                               opciones_tiempo=opciones_tiempo,
                               dias_semana_map=dias_semana_map,
                               form_data=request.form, # Mantener los datos del intento fallido
                               horario_id=horario_id)


    # Método GET: Mostrar el formulario con los datos del turno actual
    return render_template('empleados/form_editar_turno.html', 
                           turno_actual=turno_actual, 
                           empleado=empleado,
                           opciones_tiempo=opciones_tiempo,
                           dias_semana_map=dias_semana_map,
                           horario_id=horario_id) # Pasar el ID para la action URL del form

# --- RUTAS PARA AUSENCIAS DE EMPLEADOS ---

@main_bp.route('/empleados/<int:empleado_id>/ausencias', methods=['GET'])
@login_required
@admin_required
def gestionar_ausencias_empleado(empleado_id):
    db_conn = get_db()
    cursor_empleado = None
    cursor_ausencias = None
    empleado = None
    ausencias_empleado = []

    try:
        cursor_empleado = db_conn.cursor(dictionary=True)
        cursor_empleado.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_empleado.fetchone()

        if not empleado:
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        cursor_ausencias = db_conn.cursor(dictionary=True)
        # CORRECCIÓN EN LA SIGUIENTE CONSULTA SQL:
        sql_ausencias = """
            SELECT id, 
                   DATE_FORMAT(fecha_hora_inicio, '%d/%m/%Y %H:%i') AS inicio_f,
                   DATE_FORMAT(fecha_hora_fin, '%d/%m/%Y %H:%i') AS fin_f,
                   fecha_hora_inicio, fecha_hora_fin, -- Mantenemos las originales para lógica futura (ej. editar)
                   tipo_ausencia, descripcion, aprobado
            FROM ausencias_empleado 
            WHERE empleado_id = %s 
            ORDER BY fecha_hora_inicio DESC
        """
        cursor_ausencias.execute(sql_ausencias, (empleado_id,))
        ausencias_empleado = cursor_ausencias.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al cargar datos de ausencias: {err}", "danger")
        current_app.logger.error(f"Error DB en gestionar_ausencias_empleado (Empleado ID: {empleado_id}): {err}")
        if not empleado: 
             return redirect(url_for('main.listar_empleados'))
        # ausencias_empleado se quedará vacía
    finally:
        if cursor_empleado: cursor_empleado.close()
        if cursor_ausencias: cursor_ausencias.close()
    
    if not empleado: 
        return redirect(url_for('main.listar_empleados'))

    tipos_ausencia_comunes = ["Vacaciones", "Permiso Médico", "Permiso Personal", "Capacitación", "Día Libre Compensatorio", "Bloqueo Agenda"]

    return render_template('empleados/gestionar_ausencias.html', 
                           empleado=empleado, 
                           ausencias=ausencias_empleado,
                           tipos_ausencia_comunes=tipos_ausencia_comunes)

@main_bp.route('/empleados/<int:empleado_id>/ausencias/nueva', methods=['POST'])
@login_required
@admin_required
def agregar_ausencia_empleado(empleado_id):
    # Validar que el empleado exista
    db_conn = get_db()
    cursor_check_empleado = None
    try:
        cursor_check_empleado = db_conn.cursor(dictionary=True)
        cursor_check_empleado.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cursor_check_empleado.fetchone():
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))
    except mysql.connector.Error as err_check:
        flash(f"Error al verificar empleado: {err_check}", "danger")
        return redirect(url_for('main.gestionar_ausencias_empleado', empleado_id=empleado_id))
    finally:
        if cursor_check_empleado: cursor_check_empleado.close()

    fecha_hora_inicio_str = request.form.get('fecha_hora_inicio') # Espera YYYY-MM-DDTHH:MM
    fecha_hora_fin_str = request.form.get('fecha_hora_fin')       # Espera YYYY-MM-DDTHH:MM
    tipo_ausencia = request.form.get('tipo_ausencia')
    descripcion = request.form.get('descripcion')
    # 'aprobado' podría venir de un checkbox, si no, asumimos True por ahora
    aprobado = 'aprobado' in request.form 

    errores = []
    fecha_hora_inicio = None
    fecha_hora_fin = None

    if not fecha_hora_inicio_str: errores.append("Fecha y hora de inicio son obligatorias.")
    if not fecha_hora_fin_str: errores.append("Fecha y hora de fin son obligatorias.")
    if not tipo_ausencia: errores.append("El tipo de ausencia es obligatorio.")

    if fecha_hora_inicio_str and fecha_hora_fin_str:
        try:
            fecha_hora_inicio = datetime.fromisoformat(fecha_hora_inicio_str)
            fecha_hora_fin = datetime.fromisoformat(fecha_hora_fin_str)
            if fecha_hora_fin <= fecha_hora_inicio:
                errores.append("La fecha/hora de fin debe ser posterior a la fecha/hora de inicio.")
        except ValueError:
            errores.append("Formato de fecha/hora inválido.")

    # --- Validación de Solapamiento de Ausencias ---
    if not errores: # Solo si no hay errores previos
        cursor_solapamiento = None
        try:
            cursor_solapamiento = db_conn.cursor(dictionary=True)
            cursor_solapamiento.execute("""
                SELECT id FROM ausencias_empleado 
                WHERE empleado_id = %s 
                AND (
                    (%s < fecha_hora_fin AND %s > fecha_hora_inicio)
                )
            """, (empleado_id, fecha_hora_inicio, fecha_hora_fin)) # Parámetros para la consulta
            
            if cursor_solapamiento.fetchone():
                errores.append("El período de ausencia se solapa con otra ausencia existente para este empleado.")
        except mysql.connector.Error as err_solap:
            current_app.logger.error(f"Error DB verificando solapamiento de ausencias: {err_solap}")
            errores.append("Error al verificar solapamiento de ausencias.")
        finally:
            if cursor_solapamiento: cursor_solapamiento.close()
    # --- Fin Validación de Solapamiento ---

    if errores:
        for error in errores:
            flash(error, 'warning')
    else:
        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            sql = """INSERT INTO ausencias_empleado 
                        (empleado_id, fecha_hora_inicio, fecha_hora_fin, tipo_ausencia, descripcion, aprobado) 
                     VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor_insert.execute(sql, (empleado_id, fecha_hora_inicio, fecha_hora_fin, tipo_ausencia, descripcion, aprobado))
            db_conn.commit()
            flash("Ausencia registrada exitosamente.", "success")
        except mysql.connector.Error as err_insert:
            db_conn.rollback()
            flash(f"Error al registrar la ausencia: {err_insert}", "danger")
            current_app.logger.error(f"Error DB en agregar_ausencia_empleado (Empleado ID: {empleado_id}): {err_insert}")
        finally:
            if cursor_insert: cursor_insert.close()
            
    return redirect(url_for('main.gestionar_ausencias_empleado', empleado_id=empleado_id))

@main_bp.route('/ausencias_empleado/editar/<int:ausencia_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_ausencia_empleado(ausencia_id):
    db_conn = get_db()
    cursor = None # Para uso general

    # Obtener la ausencia actual y el empleado_id asociado
    ausencia_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        # Necesitamos empleado_id para redirigir y para el título/contexto
        cursor.execute("SELECT * FROM ausencias_empleado WHERE id = %s", (ausencia_id,))
        ausencia_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la ausencia: {err}", "danger")
        current_app.logger.error(f"Error DB buscando ausencia en editar_ausencia_empleado (ID: {ausencia_id}): {err}")
        return redirect(url_for('main.listar_empleados')) # Fallback general
    finally:
        if cursor: cursor.close()

    if not ausencia_actual:
        flash(f"Ausencia con ID {ausencia_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_empleados'))

    empleado_id_actual = ausencia_actual['empleado_id']

    # Obtener info del empleado para el título y contexto
    empleado = None
    cursor_emp = None
    try:
        cursor_emp = db_conn.cursor(dictionary=True)
        cursor_emp.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id_actual,))
        empleado = cursor_emp.fetchone()
    except mysql.connector.Error as err_emp:
        flash(f"Error al cargar datos del empleado asociado: {err_emp}", "danger")
        # Continuar podría ser posible si solo falló cargar el nombre del empleado
    finally:
        if cursor_emp: cursor_emp.close()
    
    if not empleado: # Si el empleado no se encuentra, es un problema de integridad o error grave
        flash("Empleado asociado a la ausencia no encontrado.", "danger")
        return redirect(url_for('main.listar_empleados'))


    tipos_ausencia_comunes = ["Vacaciones", "Permiso Médico", "Permiso Personal", "Capacitación", "Día Libre Compensatorio", "Bloqueo Agenda"]

    if request.method == 'POST':
        fecha_hora_inicio_str = request.form.get('fecha_hora_inicio')
        fecha_hora_fin_str = request.form.get('fecha_hora_fin')
        tipo_ausencia = request.form.get('tipo_ausencia')
        descripcion = request.form.get('descripcion')
        aprobado = 'aprobado' in request.form

        errores = []
        fecha_hora_inicio = None
        fecha_hora_fin = None

        if not fecha_hora_inicio_str: errores.append("Fecha y hora de inicio son obligatorias.")
        if not fecha_hora_fin_str: errores.append("Fecha y hora de fin son obligatorias.")
        if not tipo_ausencia: errores.append("El tipo de ausencia es obligatorio.")

        if fecha_hora_inicio_str and fecha_hora_fin_str:
            try:
                fecha_hora_inicio = datetime.fromisoformat(fecha_hora_inicio_str)
                fecha_hora_fin = datetime.fromisoformat(fecha_hora_fin_str)
                if fecha_hora_fin <= fecha_hora_inicio:
                    errores.append("La fecha/hora de fin debe ser posterior a la fecha/hora de inicio.")
            except ValueError:
                errores.append("Formato de fecha/hora inválido.")

        # Validación de Solapamiento (excluyendo la ausencia actual que se está editando)
        if not errores:
            cursor_solap = None
            try:
                cursor_solap = db_conn.cursor(dictionary=True)
                cursor_solap.execute("""
                    SELECT id FROM ausencias_empleado 
                    WHERE empleado_id = %s 
                    AND id != %s  -- Excluir la ausencia actual de la comprobación
                    AND (
                        (%s < fecha_hora_fin AND %s > fecha_hora_inicio)
                    )
                """, (empleado_id_actual, ausencia_id, fecha_hora_inicio, fecha_hora_fin))
                if cursor_solap.fetchone():
                    errores.append("El período de ausencia modificado se solapa con otra ausencia existente.")
            except mysql.connector.Error as err_solap:
                current_app.logger.error(f"Error DB verificando solapamiento en edición de ausencia: {err_solap}")
                errores.append("Error al verificar solapamiento de ausencias.")
            finally:
                if cursor_solap: cursor_solap.close()
        
        if errores:
            for error in errores:
                flash(error, 'warning')
            # Volver a renderizar el form de edición con los datos que el usuario intentó enviar
            # Necesitamos pasar 'ausencia' (que es ausencia_actual), 'empleado', etc.
            return render_template('empleados/form_editar_ausencia.html',
                                   ausencia=ausencia_actual, 
                                   empleado=empleado,
                                   tipos_ausencia_comunes=tipos_ausencia_comunes,
                                   form_data=request.form, # Para repoblar con lo que intentó el usuario
                                   ausencia_id=ausencia_id)
        else:
            # Actualizar la ausencia en la BD
            cursor_upd = None
            try:
                cursor_upd = db_conn.cursor()
                sql_update = """UPDATE ausencias_empleado SET 
                                    fecha_hora_inicio = %s, fecha_hora_fin = %s, 
                                    tipo_ausencia = %s, descripcion = %s, aprobado = %s
                                WHERE id = %s"""
                cursor_upd.execute(sql_update, (fecha_hora_inicio, fecha_hora_fin, tipo_ausencia, descripcion, aprobado, ausencia_id))
                db_conn.commit()
                flash("Ausencia actualizada exitosamente.", "success")
                return redirect(url_for('main.gestionar_ausencias_empleado', empleado_id=empleado_id_actual))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                flash(f"Error al actualizar la ausencia: {err_upd}", "danger")
                current_app.logger.error(f"Error DB en POST editar_ausencia_empleado (ID: {ausencia_id}): {err_upd}")
            finally:
                if cursor_upd: cursor_upd.close()
            
            # Si llega aquí es por error de BD en el update, re-renderizar
            return render_template('empleados/form_editar_ausencia.html',
                                   ausencia=ausencia_actual, 
                                   empleado=empleado,
                                   tipos_ausencia_comunes=tipos_ausencia_comunes,
                                   form_data=request.form,
                                   ausencia_id=ausencia_id)

    # Método GET: Mostrar el formulario con los datos actuales de la ausencia
    # Convertir fechas a string para el input datetime-local si son objetos datetime
    if isinstance(ausencia_actual['fecha_hora_inicio'], datetime):
        ausencia_actual['fecha_hora_inicio_str'] = ausencia_actual['fecha_hora_inicio'].strftime('%Y-%m-%dT%H:%M')
    else: # Si ya es string (no debería pasar si viene de la BD directamente)
        ausencia_actual['fecha_hora_inicio_str'] = ausencia_actual['fecha_hora_inicio']
        
    if isinstance(ausencia_actual['fecha_hora_fin'], datetime):
        ausencia_actual['fecha_hora_fin_str'] = ausencia_actual['fecha_hora_fin'].strftime('%Y-%m-%dT%H:%M')
    else:
        ausencia_actual['fecha_hora_fin_str'] = ausencia_actual['fecha_hora_fin']

    return render_template('empleados/form_editar_ausencia.html', 
                           ausencia=ausencia_actual, 
                           empleado=empleado,
                           tipos_ausencia_comunes=tipos_ausencia_comunes,
                           ausencia_id=ausencia_id) # Pasar el ID para la action URL del form

@main_bp.route('/ausencias_empleado/eliminar/<int:ausencia_id>', methods=['GET']) # Usamos GET por simplicidad con confirmación JS
@login_required
@admin_required
def eliminar_ausencia_empleado(ausencia_id):
    """
    Elimina un registro de ausencia específico.
    """
    empleado_id_para_redirect = None
    db_conn = get_db()
    cursor_find = None
    cursor_delete = None

    try:
        # Primero, encontrar el empleado_id asociado con esta ausencia_id para poder redirigir correctamente
        cursor_find = db_conn.cursor(dictionary=True)
        cursor_find.execute("SELECT empleado_id FROM ausencias_empleado WHERE id = %s", (ausencia_id,))
        ausencia_info = cursor_find.fetchone()

        if not ausencia_info:
            flash(f"Registro de ausencia con ID {ausencia_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados')) 
        
        empleado_id_para_redirect = ausencia_info['empleado_id']

        # Proceder a eliminar el registro de ausencia
        cursor_delete = db_conn.cursor()
        cursor_delete.execute("DELETE FROM ausencias_empleado WHERE id = %s", (ausencia_id,))
        db_conn.commit()

        if cursor_delete.rowcount > 0:
            flash("Registro de ausencia eliminado exitosamente.", "success")
        else:
            flash(f"No se pudo eliminar el registro de ausencia con ID {ausencia_id}.", "warning")

    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f"Error al eliminar el registro de ausencia: {err}", "danger")
        current_app.logger.error(f"Error DB en eliminar_ausencia_empleado (Ausencia ID: {ausencia_id}): {err}")
        # Intentar redirigir a la página de ausencias del empleado si tenemos el ID, sino a la lista general
        if empleado_id_para_redirect:
            return redirect(url_for('main.gestionar_ausencias_empleado', empleado_id=empleado_id_para_redirect))
        else:
            return redirect(url_for('main.listar_empleados'))
    finally:
        if cursor_find:
            cursor_find.close()
        if cursor_delete:
            cursor_delete.close()
    
    # Redirigir a la página de gestión de ausencias del empleado correspondiente
    if empleado_id_para_redirect:
        return redirect(url_for('main.gestionar_ausencias_empleado', empleado_id=empleado_id_para_redirect))
    else:
        return redirect(url_for('main.listar_empleados')) # Fallback

@main_bp.route('/productos/categorias')
@login_required
def listar_categorias_productos():
    """
    Muestra la lista de todas las categorías de productos.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_productos ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las categorías de productos: {err}", "danger")
        current_app.logger.error(f"Error en listar_categorias_productos: {err}")
        lista_de_categorias = []
        
    return render_template('productos/lista_categorias_productos.html', 
                           categorias=lista_de_categorias)

@main_bp.route('/productos/categorias/nueva', methods=['GET', 'POST'])
@login_required
def nueva_categoria_producto():
    """
    Muestra el formulario para registrar una nueva categoría de producto (GET)
    y procesa la creación de la categoría (POST).
    """
    # Para el GET, preparamos datos para el título del formulario
    form_titulo = "Registrar Nueva Categoría de Producto"
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')

        if not nombre:
            flash('El nombre de la categoría es obligatorio.', 'warning')
            # Volvemos a renderizar el formulario, pasando los datos ingresados y el título
            return render_template('productos/form_categoria_producto.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=url_for('main.nueva_categoria_producto'))

        cursor_insert = None # Definir fuera para usar en finally
        try:
            db = get_db()
            cursor_insert = db.cursor()
            sql = "INSERT INTO categorias_productos (nombre, descripcion) VALUES (%s, %s)"
            val = (nombre, descripcion)
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Categoría de producto "{nombre}" registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_categorias_productos'))
        except mysql.connector.Error as err:
            db.rollback()
            if err.errno == 1062: # Error de entrada duplicada (nombre UNIQUE)
                flash(f'Error: Ya existe una categoría de producto con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la categoría de producto: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_categoria_producto (POST): {err}")
            # Volvemos a renderizar el formulario con datos y errores
            return render_template('productos/form_categoria_producto.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=url_for('main.nueva_categoria_producto'))
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío para una nueva categoría
    return render_template('productos/form_categoria_producto.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=url_for('main.nueva_categoria_producto'))

@main_bp.route('/productos/categorias/editar/<int:categoria_id>', methods=['GET', 'POST'])
@login_required
def editar_categoria_producto(categoria_id):
    """
    Muestra el formulario para editar una categoría de producto existente (GET)
    y procesa la actualización (POST).
    """
    db_conn = get_db()
    cursor = None # Para uso general

    # Obtener la categoría actual para editar
    categoria_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_productos WHERE id = %s", (categoria_id,))
        categoria_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la categoría de producto: {err}", "danger")
        current_app.logger.error(f"Error DB buscando categoría de producto en editar (ID: {categoria_id}): {err}")
        return redirect(url_for('main.listar_categorias_productos'))
    finally:
        if cursor: # Solo cerrar si se abrió
            cursor.close()
            cursor = None # Resetear para posible uso posterior

    if not categoria_actual:
        flash(f"Categoría de producto con ID {categoria_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_categorias_productos'))

    form_titulo = f"Editar Categoría: {categoria_actual['nombre']}"
    action_url_form = url_for('main.editar_categoria_producto', categoria_id=categoria_id)

    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre')
        descripcion_nueva = request.form.get('descripcion')
        
        errores = []
        if not nombre_nuevo:
            errores.append('El nombre de la categoría es obligatorio.')

        # Validar unicidad del nombre si ha cambiado
        if nombre_nuevo and nombre_nuevo.lower() != categoria_actual['nombre'].lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM categorias_productos WHERE nombre = %s AND id != %s", (nombre_nuevo, categoria_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra categoría de producto con el nombre "{nombre_nuevo}".')
            except mysql.connector.Error as err_check_nombre:
                current_app.logger.error(f"Error DB verificando nombre en editar_categoria_producto: {err_check_nombre}")
                errores.append("Error al verificar la disponibilidad del nombre.")
            finally:
                if cursor: 
                    cursor.close()
                    cursor = None

        if errores:
            for error_msg in errores: # Cambiado 'error' a 'error_msg' para evitar conflicto de variable
                flash(error_msg, 'warning')
            return render_template('productos/form_categoria_producto.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   categoria_prod=categoria_actual, # Pasar datos originales para repoblar
                                   form_data=request.form) # Pasar datos del intento fallido
        else:
            # Actualizar la categoría en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = "UPDATE categorias_productos SET nombre = %s, descripcion = %s WHERE id = %s"
                cursor.execute(sql_update, (nombre_nuevo, descripcion_nueva, categoria_id))
                db_conn.commit()
                flash(f'Categoría de producto "{nombre_nuevo}" actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_categorias_productos'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                flash(f"Error al actualizar la categoría de producto: {err_upd}", "danger")
                current_app.logger.error(f"Error DB en POST editar_categoria_producto (ID: {categoria_id}): {err_upd}")
            finally:
                if cursor: 
                    cursor.close()
            
            # Si llega aquí es por error de BD en el update, re-renderizar
            return render_template('productos/form_categoria_producto.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   categoria_prod=categoria_actual,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales de la categoría
    return render_template('productos/form_categoria_producto.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           categoria_prod=categoria_actual) # 'categoria_prod' para que coincida con el form

@main_bp.route('/productos/categorias/eliminar/<int:categoria_id>', methods=['GET']) # Usaremos GET con confirmación JS
@login_required
def eliminar_categoria_producto(categoria_id):
    """
    Elimina una categoría de producto existente.
    """
    db_conn = get_db()
    cursor = None
    try:
        # ** IMPORTANTE: Validación de Productos Asociados (Futuro) **
        # Antes de eliminar una categoría, deberíamos verificar si hay productos
        # en la tabla 'productos' (que aún no hemos creado) que pertenezcan a esta categoría.
        # Si los hay, NO deberíamos permitir la eliminación o deberíamos advertir al usuario.
        # Ejemplo de cómo sería (cuando tengamos la tabla 'productos'):
        #
        # cursor_check = db_conn.cursor(dictionary=True)
        # cursor_check.execute("SELECT COUNT(*) as count FROM productos WHERE categoria_id = %s", (categoria_id,))
        # if cursor_check.fetchone()['count'] > 0:
        #     flash("No se puede eliminar la categoría porque tiene productos asociados. Reasigne o elimine esos productos primero.", "warning")
        #     cursor_check.close()
        #     return redirect(url_for('main.listar_categorias_productos'))
        # cursor_check.close()
        #
        # Por ahora, procederemos con la eliminación directa.

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM categorias_productos WHERE id = %s", (categoria_id,))
        db_conn.commit()

        if cursor.rowcount > 0:
            flash('Categoría de producto eliminada exitosamente!', 'success')
        else:
            flash('No se encontró la categoría de producto o no se pudo eliminar.', 'warning')
            
    except mysql.connector.Error as err:
        db_conn.rollback()
        # Error común si hay una restricción de clave foránea (ej. productos usándola)
        if '1451' in str(err): 
            flash('No se puede eliminar esta categoría porque tiene productos asociados. Por favor, reasigne o elimine esos productos primero.', 'danger')
        else:
            flash(f"Error al eliminar la categoría de producto: {err}", 'danger')
        current_app.logger.error(f"Error DB en eliminar_categoria_producto (ID: {categoria_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_categorias_productos'))

# --- RUTAS PARA PRODUCTOS ---

# En app/routes.py

@main_bp.route('/productos')
@login_required
def listar_productos():
    """
    Muestra la lista de todos los productos, asegurando que se seleccionen todas
    las columnas necesarias para la plantilla.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Consulta SQL corregida para incluir TODAS las columnas necesarias
        sql = """
            SELECT 
                p.id, p.nombre, p.stock_actual, p.stock_minimo, p.activo,
                p.precio_venta, p.comision_vendedor_monto,
                p.contenido_neto_valor, p.unidad_medida,
                cp.nombre AS categoria_nombre,
                m.nombre AS marca_nombre, 
                pr.nombre_empresa AS proveedor_nombre
            FROM productos p
            LEFT JOIN categorias_productos cp ON p.categoria_id = cp.id
            LEFT JOIN marcas m ON p.marca_id = m.id 
            LEFT JOIN proveedores pr ON p.proveedor_id = pr.id
            ORDER BY p.nombre
        """
        cursor.execute(sql)
        lista_de_productos = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los productos: {err}", "danger")
        current_app.logger.error(f"Error en listar_productos: {err}")
        lista_de_productos = []
        
    return render_template('productos/lista_productos.html', productos=lista_de_productos)


@main_bp.route('/productos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_producto():
    db_conn = get_db()
    categorias_prod, marcas_todas, proveedores_todos = [], [], []
    try:
        # Cargar datos para desplegables
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM categorias_productos WHERE activo = TRUE ORDER BY nombre")
            categorias_prod = cursor.fetchall()
            cursor.execute("SELECT id, nombre FROM marcas WHERE activo = TRUE ORDER BY nombre")
            marcas_todas = cursor.fetchall()
            cursor.execute("SELECT id, nombre_empresa FROM proveedores WHERE activo = TRUE ORDER BY nombre_empresa")
            proveedores_todos = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar datos del formulario: {e}", "danger")

    if request.method == 'POST':
        try:
            # Recoger datos del formulario
            nombre = request.form.get('nombre')
            codigo_barras = request.form.get('codigo_barras', '').strip() or None
            descripcion = request.form.get('descripcion', '').strip() or None
            categoria_id = request.form.get('categoria_id', type=int)
            marca_id = request.form.get('marca_id', type=int) or None
            proveedor_id = request.form.get('proveedor_id', type=int) or None
            precio_compra_str = request.form.get('precio_compra')
            precio_venta_str = request.form.get('precio_venta')
            comision_monto_str = request.form.get('comision_vendedor_monto')
            stock_actual = request.form.get('stock_actual', '0', type=int)
            stock_minimo = request.form.get('stock_minimo', '0', type=int)
            activo = 'activo' in request.form
            
            # Validaciones y conversiones
            if not nombre or not categoria_id or not precio_venta_str:
                raise ValueError("Nombre, Categoría y Precio de Venta son obligatorios.")
            
            precio_venta = float(precio_venta_str)
            precio_compra = float(precio_compra_str) if precio_compra_str else None
            comision_vendedor_monto = float(comision_monto_str) if comision_monto_str else None
            
            with db_conn.cursor() as cursor:
                sql = """INSERT INTO productos 
                            (nombre, codigo_barras, descripcion, categoria_id, marca_id, proveedor_id, 
                             precio_compra, precio_venta, comision_vendedor_monto, stock_actual, stock_minimo, activo)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                val = (nombre, codigo_barras, descripcion, categoria_id, marca_id, proveedor_id,
                       precio_compra, precio_venta, comision_vendedor_monto, stock_actual, stock_minimo, activo)
                cursor.execute(sql, val)
            db_conn.commit()
            flash(f'Producto "{nombre}" registrado exitosamente!', 'success')
            return redirect(url_for('main.listar_productos'))
            
        except (ValueError, mysql.connector.Error) as e:
            db_conn.rollback()
            flash(f"Error al registrar el producto: {e}", "warning")
    
    return render_template('productos/form_producto.html', 
                           form_data=request.form if request.method == 'POST' else None,
                           es_nueva=True, titulo_form="Registrar Nuevo Producto",
                           action_url=url_for('main.nuevo_producto'),
                           categorias_prod=categorias_prod, marcas_todas=marcas_todas, proveedores_todos=proveedores_todos)


@main_bp.route('/productos/editar/<int:producto_id>', methods=['GET', 'POST'])
@login_required
def editar_producto(producto_id):
    """
    Maneja la edición de un producto existente, con el campo de comisión
    actualizado a un monto fijo.
    """
    db_conn = get_db()
    
    # Cargar datos para los menús desplegables (necesario para GET y para POST con error)
    categorias_prod, marcas_todas, proveedores_todos = [], [], []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM categorias_productos WHERE activo = TRUE ORDER BY nombre")
            categorias_prod = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM marcas WHERE activo = TRUE ORDER BY nombre")
            marcas_todas = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre_empresa FROM proveedores WHERE activo = TRUE ORDER BY nombre_empresa")
            proveedores_todos = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar datos del formulario: {e}", "danger")

    # Obtener el producto actual que se está editando
    with db_conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM productos WHERE id = %s", (producto_id,))
        producto_actual = cursor.fetchone()
    
    if not producto_actual:
        flash("Producto no encontrado.", "warning")
        return redirect(url_for('main.listar_productos'))

    # --- Lógica POST ---
    if request.method == 'POST':
        try:
            # 1. Recoger datos del formulario
            nombre = request.form.get('nombre')
            codigo_barras_nuevo = request.form.get('codigo_barras', '').strip() or None
            descripcion = request.form.get('descripcion', '').strip() or None
            categoria_id = request.form.get('categoria_id', type=int)
            marca_id = request.form.get('marca_id', type=int) or None
            proveedor_id = request.form.get('proveedor_id', type=int) or None
            precio_compra_str = request.form.get('precio_compra')
            precio_venta_str = request.form.get('precio_venta')
            comision_monto_str = request.form.get('comision_vendedor_monto') # <-- CAMPO ACTUALIZADO
            stock_actual = request.form.get('stock_actual', '0', type=int)
            stock_minimo = request.form.get('stock_minimo', '0', type=int)
            activo = 'activo' in request.form

            # 2. Validaciones
            errores = []
            if not nombre or not categoria_id or not precio_venta_str:
                errores.append("Nombre, Categoría y Precio de Venta son obligatorios.")
            
            # Validar unicidad del código de barras si ha cambiado
            if codigo_barras_nuevo and codigo_barras_nuevo != producto_actual.get('codigo_barras'):
                with db_conn.cursor(dictionary=True) as cursor:
                    cursor.execute("SELECT id FROM productos WHERE codigo_barras = %s AND id != %s", (codigo_barras_nuevo, producto_id))
                    if cursor.fetchone():
                        errores.append(f"El código de barras '{codigo_barras_nuevo}' ya está en uso.")
            
            if errores:
                raise ValueError("; ".join(errores))

            # 3. Conversión de datos y construcción de la consulta
            precio_venta = float(precio_venta_str)
            precio_compra = float(precio_compra_str) if precio_compra_str else None
            comision_vendedor_monto = float(comision_monto_str) if comision_monto_str else None

            with db_conn.cursor() as cursor:
                sql_update = """UPDATE productos SET 
                                    nombre = %s, codigo_barras = %s, descripcion = %s, categoria_id = %s,
                                    marca_id = %s, proveedor_id = %s, precio_compra = %s, precio_venta = %s,
                                    comision_vendedor_monto = %s, stock_actual = %s, stock_minimo = %s, activo = %s
                                WHERE id = %s"""
                val_update = (
                    nombre, codigo_barras_nuevo, descripcion, categoria_id, marca_id, proveedor_id,
                    precio_compra, precio_venta, comision_vendedor_monto, stock_actual, stock_minimo, 
                    activo, producto_id
                )
                cursor.execute(sql_update, val_update)
            
            db_conn.commit()
            flash(f'Producto "{nombre}" actualizado exitosamente!', 'success')
            return redirect(url_for('main.listar_productos'))

        except (ValueError, mysql.connector.Error) as e:
            db_conn.rollback()
            flash(f"Error al actualizar el producto: {e}", "warning")
            # Volver a renderizar con los datos y el error
            return render_template('productos/form_producto.html', 
                                   form_data=request.form, es_nueva=False, 
                                   titulo_form=f"Editar Producto (Error)",
                                   action_url=url_for('main.editar_producto', producto_id=producto_id),
                                   producto=producto_actual,
                                   categorias_prod=categorias_prod, marcas_todas=marcas_todas, proveedores_todos=proveedores_todos)

    # --- Lógica GET ---
    return render_template('productos/form_producto.html', 
                           es_nueva=False, 
                           titulo_form=f"Editar Producto: {producto_actual.get('nombre')}",
                           action_url=url_for('main.editar_producto', producto_id=producto_id),
                           producto=producto_actual,
                           categorias_prod=categorias_prod,
                           marcas_todas=marcas_todas,
                           proveedores_todos=proveedores_todos)

        
@main_bp.route('/marcas')
@login_required
def listar_marcas():
    """
    Muestra la lista de todas las marcas de productos.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion, activo FROM marcas ORDER BY nombre")
        lista_de_marcas = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las marcas: {err}", "danger")
        current_app.logger.error(f"Error en listar_marcas: {err}")
        lista_de_marcas = []
        
    return render_template('marcas/lista_marcas.html', marcas=lista_de_marcas)

@main_bp.route('/marcas/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_marca():
    """
    Muestra el formulario para registrar una nueva marca (GET)
    y procesa la creación de la marca (POST).
    """
    form_titulo = "Registrar Nueva Marca"
    action_url_form = url_for('main.nueva_marca') # Para el action del form

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        activo = 'activo' in request.form # Checkbox

        if not nombre:
            flash('El nombre de la marca es obligatorio.', 'warning')
            return render_template('marcas/form_marca.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

        cursor_insert = None
        try:
            db = get_db()
            cursor_insert = db.cursor()
            sql = "INSERT INTO marcas (nombre, descripcion, activo) VALUES (%s, %s, %s)"
            val = (nombre, descripcion, activo)
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Marca "{nombre}" registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_marcas'))
        except mysql.connector.Error as err:
            db.rollback()
            if err.errno == 1062: # Error de entrada duplicada (nombre UNIQUE)
                flash(f'Error: Ya existe una marca con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la marca: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_marca (POST): {err}")
            return render_template('marcas/form_marca.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('marcas/form_marca.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form)
    
@main_bp.route('/marcas/editar/<int:marca_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_marca(marca_id):
    """
    Muestra el formulario para editar una marca existente (GET)
    y procesa la actualización (POST).
    """
    db_conn = get_db()
    cursor = None 

    # Obtener la marca actual para editar
    marca_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion, activo FROM marcas WHERE id = %s", (marca_id,))
        marca_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la marca: {err}", "danger")
        current_app.logger.error(f"Error DB buscando marca en editar (ID: {marca_id}): {err}")
        return redirect(url_for('main.listar_marcas'))
    finally:
        if cursor: 
            cursor.close()
            cursor = None 

    if not marca_actual:
        flash(f"Marca con ID {marca_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_marcas'))

    form_titulo = f"Editar Marca: {marca_actual['nombre']}"
    # La URL a la que el formulario hará POST
    action_url_form = url_for('main.editar_marca', marca_id=marca_id) 

    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre')
        descripcion_nueva = request.form.get('descripcion')
        activo_nuevo = 'activo' in request.form
        
        errores = []
        if not nombre_nuevo:
            errores.append('El nombre de la marca es obligatorio.')

        # Validar unicidad del nombre si ha cambiado
        if nombre_nuevo and nombre_nuevo.lower() != marca_actual['nombre'].lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM marcas WHERE nombre = %s AND id != %s", (nombre_nuevo, marca_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra marca con el nombre "{nombre_nuevo}".')
            except mysql.connector.Error as err_check_nombre:
                current_app.logger.error(f"Error DB verificando nombre en editar_marca: {err_check_nombre}")
                errores.append("Error al verificar la disponibilidad del nombre de la marca.")
            finally:
                if cursor: 
                    cursor.close()
                    cursor = None
        
        if errores:
            for error_msg in errores:
                flash(error_msg, 'warning')
            # Volver a mostrar el formulario de edición con los errores y los datos que el usuario intentó enviar
            return render_template('marcas/form_marca.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   marca_item=marca_actual, # Datos originales para el título y contexto
                                   form_data=request.form) # Datos del intento fallido para repoblar
        else:
            # Actualizar la marca en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = "UPDATE marcas SET nombre = %s, descripcion = %s, activo = %s WHERE id = %s"
                cursor.execute(sql_update, (nombre_nuevo, descripcion_nueva, activo_nuevo, marca_id))
                db_conn.commit()
                flash(f'Marca "{nombre_nuevo}" actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_marcas'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                # Manejar error de nombre duplicado en el UPDATE también (por si acaso)
                if err_upd.errno == 1062:
                     flash(f'Error: Ya existe una marca con el nombre "{nombre_nuevo}".', 'danger')
                else:
                    flash(f"Error al actualizar la marca: {err_upd}", 'danger')
                current_app.logger.error(f"Error DB en POST editar_marca (ID: {marca_id}): {err_upd}")
            finally:
                if cursor: 
                    cursor.close()
            
            # Si llega aquí es por error de BD en el update, re-renderizar
            return render_template('marcas/form_marca.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   marca_item=marca_actual,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales de la marca
    # La plantilla form_marca.html espera 'marca_item' para el data_source en modo edición
    return render_template('marcas/form_marca.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           marca_item=marca_actual) 

@main_bp.route('/marcas/toggle_activo/<int:marca_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_marca(marca_id):
    """
    Cambia el estado 'activo' de una marca.
    """
    marca_actual = None
    db_conn = get_db()
    cursor = None

    try:
        cursor = db_conn.cursor(dictionary=True)
        # Obtener el estado actual de la marca
        cursor.execute("SELECT id, nombre, activo FROM marcas WHERE id = %s", (marca_id,))
        marca_actual = cursor.fetchone()

        if not marca_actual:
            flash(f'Marca con ID {marca_id} no encontrada.', 'warning')
            return redirect(url_for('main.listar_marcas'))

        nuevo_estado_activo = not marca_actual['activo'] # Invertir el estado
        
        # Usar un nuevo cursor para la actualización o el mismo si se gestiona bien
        # Para evitar problemas con resultados pendientes, es más seguro un nuevo cursor para la escritura
        # o cerrar y reabrir si es el mismo objeto cursor.
        # Por simplicidad, cerramos el de lectura y abrimos uno para escritura si fuera necesario,
        # o simplemente usamos uno nuevo para la operación de update.
        if cursor: # Cerrar el cursor de lectura si se usó y está abierto
            cursor.close()
            cursor = None 

        cursor_update = db_conn.cursor() # Nuevo cursor para la operación de escritura
        sql_update = "UPDATE marcas SET activo = %s WHERE id = %s"
        cursor_update.execute(sql_update, (nuevo_estado_activo, marca_id))
        db_conn.commit()
        
        mensaje_estado = "activada" if nuevo_estado_activo else "desactivada"
        flash(f'La marca "{marca_actual["nombre"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
        if cursor_update: cursor_update.close() # Cerrar cursor de escritura
        
    except mysql.connector.Error as err:
        if db_conn: # Solo hacer rollback si la conexión existe y está activa
            db_conn.rollback()
        flash(f'Error al cambiar el estado de la marca: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_marca (ID: {marca_id}): {err}")
    finally:
        # Asegurarse de que cualquier cursor abierto se cierre
        if cursor and (not hasattr(cursor, 'is_closed') or not cursor.is_closed()): # Si el primer cursor sigue existiendo
            cursor.close()
        # cursor_update ya se cierra en el try si se crea.

    return redirect(url_for('main.listar_marcas'))

@main_bp.route('/productos/toggle_activo/<int:producto_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_producto(producto_id):
    """
    Cambia el estado 'activo' de un producto.
    """
    producto_actual = None
    db_conn = get_db()
    cursor = None # Para leer
    cursor_update = None # Para escribir

    try:
        cursor = db_conn.cursor(dictionary=True)
        # Obtener el estado actual del producto
        cursor.execute("SELECT id, nombre, activo FROM productos WHERE id = %s", (producto_id,))
        producto_actual = cursor.fetchone()

        if not producto_actual:
            flash(f'Producto con ID {producto_id} no encontrado.', 'warning')
            return redirect(url_for('main.listar_productos'))

        nuevo_estado_activo = not producto_actual['activo'] # Invertir el estado
        
        # Cerrar el cursor de lectura antes de la operación de escritura si es el mismo objeto cursor
        # o simplemente usar un nuevo cursor para la escritura.
        if cursor:
            cursor.close()
            cursor = None 

        cursor_update = db_conn.cursor()
        sql_update = "UPDATE productos SET activo = %s WHERE id = %s"
        cursor_update.execute(sql_update, (nuevo_estado_activo, producto_id))
        db_conn.commit()
        
        mensaje_estado = "activado" if nuevo_estado_activo else "desactivado"
        flash(f'El producto "{producto_actual["nombre"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn: # Solo hacer rollback si la conexión existe
            db_conn.rollback()
        flash(f'Error al cambiar el estado del producto: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_producto (ID: {producto_id}): {err}")
    finally:
        # Asegurarse de que todos los cursores que podrían haber sido abiertos se cierren
        if cursor: # Por si hubo una excepción antes de cerrarlo en el try
            cursor.close()
        if cursor_update:
            cursor_update.close()

    return redirect(url_for('main.listar_productos'))

# --- Fin de Rutas para Productos ---

# --- RUTAS PARA PROVEEDORES ---

@main_bp.route('/proveedores')
@login_required
@admin_required
def listar_proveedores():
    """
    Muestra la lista de todos los proveedores.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, nombre_empresa, ruc, nombre_contacto, telefono, email, activo 
            FROM proveedores 
            ORDER BY nombre_empresa
        """)
        lista_de_proveedores = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los proveedores: {err}", "danger")
        current_app.logger.error(f"Error en listar_proveedores: {err}")
        lista_de_proveedores = []
        
    return render_template('proveedores/lista_proveedores.html', proveedores=lista_de_proveedores)

@main_bp.route('/proveedores/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_proveedor():
    """
    Muestra el formulario para registrar un nuevo proveedor (GET)
    y procesa la creación del proveedor (POST).
    """
    form_titulo = "Registrar Nuevo Proveedor"
    action_url_form = url_for('main.nuevo_proveedor')

    if request.method == 'POST':
        nombre_empresa = request.form.get('nombre_empresa')
        ruc = request.form.get('ruc', '').strip()
        nombre_contacto = request.form.get('nombre_contacto', '').strip()
        telefono = request.form.get('telefono', '').strip()
        email = request.form.get('email', '').strip()
        direccion = request.form.get('direccion', '').strip()
        ciudad = request.form.get('ciudad', '').strip()
        pais = request.form.get('pais', '').strip()
        notas = request.form.get('notas', '').strip()
        activo = 'activo' in request.form

        errores = []
        if not nombre_empresa:
            errores.append('El nombre de la empresa/proveedor es obligatorio.')
        
        # Opcional: Validaciones para RUC (longitud, formato si es necesario)
        if ruc and len(ruc) > 11: # Ejemplo simple de longitud para RUC Perú
            errores.append('El RUC no debe exceder los 11 caracteres.')

        # Convertir strings vacíos a None para campos opcionales UNIQUE en BD
        ruc_db = ruc if ruc else None
        email_db = email if email else None
        nombre_contacto_db = nombre_contacto if nombre_contacto else None
        telefono_db = telefono if telefono else None
        direccion_db = direccion if direccion else None
        ciudad_db = ciudad if ciudad else None
        pais_db = pais if pais else None
        notas_db = notas if notas else None


        if errores:
            for error in errores:
                flash(error, 'warning')
            return render_template('proveedores/form_proveedor.html', 
                                   form_data=request.form, 
                                   es_nuevo=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

        cursor_insert = None
        try:
            db = get_db()
            cursor_insert = db.cursor()
            sql = """INSERT INTO proveedores 
                        (nombre_empresa, ruc, nombre_contacto, telefono, email, 
                         direccion, ciudad, pais, notas, activo) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            val = (nombre_empresa, ruc_db, nombre_contacto_db, telefono_db, email_db,
                   direccion_db, ciudad_db, pais_db, notas_db, activo)
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Proveedor "{nombre_empresa}" registrado exitosamente!', 'success')
            return redirect(url_for('main.listar_proveedores'))
        except mysql.connector.Error as err:
            db.rollback()
            # Errores comunes de UNIQUE: 1062
            if err.errno == 1062:
                if 'nombre_empresa' in err.msg:
                    flash(f'Error: Ya existe un proveedor con el nombre "{nombre_empresa}".', 'danger')
                elif 'ruc' in err.msg and ruc_db:
                    flash(f'Error: Ya existe un proveedor con el RUC "{ruc_db}".', 'danger')
                elif 'email' in err.msg and email_db:
                    flash(f'Error: Ya existe un proveedor con el email "{email_db}".', 'danger')
                else:
                    flash(f'Error de dato duplicado al registrar el proveedor: {err.msg}', 'danger')
            else:
                flash(f'Error al registrar el proveedor: {err}', 'danger')
            current_app.logger.error(f"Error en nuevo_proveedor (POST): {err}")
            return render_template('proveedores/form_proveedor.html', 
                                   form_data=request.form, 
                                   es_nuevo=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('proveedores/form_proveedor.html', 
                           es_nuevo=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form)

@main_bp.route('/proveedores/editar/<int:proveedor_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_proveedor(proveedor_id):
    db_conn = get_db()
    cursor = None 

    # Obtener el proveedor actual para editar
    proveedor_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM proveedores WHERE id = %s", (proveedor_id,))
        proveedor_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar el proveedor: {err}", "danger")
        current_app.logger.error(f"Error DB buscando proveedor en editar (ID: {proveedor_id}): {err}")
        return redirect(url_for('main.listar_proveedores'))
    finally:
        if cursor: 
            cursor.close()
            cursor = None 

    if not proveedor_actual:
        flash(f"Proveedor con ID {proveedor_id} no encontrado.", "warning")
        return redirect(url_for('main.listar_proveedores'))

    form_titulo = f"Editar Proveedor: {proveedor_actual.get('nombre_empresa', '')}"
    action_url_form = url_for('main.editar_proveedor', proveedor_id=proveedor_id) 

    if request.method == 'POST':
        nombre_empresa_nuevo = request.form.get('nombre_empresa')
        ruc_nuevo = request.form.get('ruc', '').strip()
        nombre_contacto_nuevo = request.form.get('nombre_contacto', '').strip()
        telefono_nuevo = request.form.get('telefono', '').strip()
        email_nuevo = request.form.get('email', '').strip()
        direccion_nueva = request.form.get('direccion', '').strip()
        ciudad_nueva = request.form.get('ciudad', '').strip()
        pais_nuevo = request.form.get('pais', '').strip()
        notas_nuevas = request.form.get('notas', '').strip()
        activo_nuevo = 'activo' in request.form
        
        errores = []
        if not nombre_empresa_nuevo:
            errores.append('El nombre de la empresa/proveedor es obligatorio.')
        
        if ruc_nuevo and len(ruc_nuevo) > 11:
            errores.append('El RUC no debe exceder los 11 caracteres.')

        # Convertir strings vacíos a None para campos opcionales UNIQUE en BD
        ruc_db_nuevo = ruc_nuevo if ruc_nuevo else None
        email_db_nuevo = email_nuevo if email_nuevo else None
        
        # Validaciones de unicidad SI el valor ha cambiado
        if nombre_empresa_nuevo and nombre_empresa_nuevo.lower() != proveedor_actual.get('nombre_empresa', '').lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM proveedores WHERE nombre_empresa = %s AND id != %s", (nombre_empresa_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el nombre "{nombre_empresa_nuevo}".')
            except mysql.connector.Error as err_check: current_app.logger.error(f"Error DB verificando nombre_empresa: {err_check}")
            finally: 
                if cursor: cursor.close(); cursor = None

        if ruc_db_nuevo and ruc_db_nuevo != proveedor_actual.get('ruc'):
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM proveedores WHERE ruc = %s AND id != %s", (ruc_db_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el RUC "{ruc_db_nuevo}".')
            except mysql.connector.Error as err_check: current_app.logger.error(f"Error DB verificando RUC: {err_check}")
            finally: 
                if cursor: cursor.close(); cursor = None
        
        if email_db_nuevo and email_db_nuevo.lower() != (proveedor_actual.get('email', '') or '').lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM proveedores WHERE email = %s AND id != %s", (email_db_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el email "{email_db_nuevo}".')
            except mysql.connector.Error as err_check: current_app.logger.error(f"Error DB verificando email: {err_check}")
            finally: 
                if cursor: cursor.close(); cursor = None

        if errores:
            for error_msg in errores:
                flash(error_msg, 'warning')
            return render_template('proveedores/form_proveedor.html',
                                   es_nuevo=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   proveedor=proveedor_actual, 
                                   form_data=request.form)
        else:
            # Actualizar el proveedor en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = """UPDATE proveedores SET 
                                    nombre_empresa = %s, ruc = %s, nombre_contacto = %s, 
                                    telefono = %s, email = %s, direccion = %s, 
                                    ciudad = %s, pais = %s, notas = %s, activo = %s
                                WHERE id = %s"""
                val_update = (nombre_empresa_nuevo, ruc_db_nuevo, 
                              nombre_contacto_nuevo if nombre_contacto_nuevo else None, 
                              telefono_nuevo if telefono_nuevo else None, 
                              email_db_nuevo, 
                              direccion_nueva if direccion_nueva else None, 
                              ciudad_nueva if ciudad_nueva else None, 
                              pais_nuevo if pais_nuevo else None, 
                              notas_nuevas if notas_nuevas else None, 
                              activo_nuevo, proveedor_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'Proveedor "{nombre_empresa_nuevo}" actualizado exitosamente!', 'success')
                return redirect(url_for('main.listar_proveedores'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                # Re-chequear errores de UNIQUE en el UPDATE
                if err_upd.errno == 1062:
                    if 'nombre_empresa' in err_upd.msg:
                        flash(f'Error: Ya existe un proveedor con el nombre "{nombre_empresa_nuevo}".', 'danger')
                    elif 'ruc' in err_upd.msg and ruc_db_nuevo:
                        flash(f'Error: Ya existe un proveedor con el RUC "{ruc_db_nuevo}".', 'danger')
                    elif 'email' in err_upd.msg and email_db_nuevo:
                        flash(f'Error: Ya existe un proveedor con el email "{email_db_nuevo}".', 'danger')
                    else:
                        flash(f'Error de dato duplicado al actualizar el proveedor.', 'danger')
                else:
                    flash(f"Error al actualizar el proveedor: {err_upd}", 'danger')
                current_app.logger.error(f"Error DB en POST editar_proveedor (ID: {proveedor_id}): {err_upd}")
            finally:
                if cursor: cursor.close()
            
            return render_template('proveedores/form_proveedor.html',
                                   es_nuevo=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   proveedor=proveedor_actual,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales del proveedor
    return render_template('proveedores/form_proveedor.html', 
                           es_nuevo=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           proveedor=proveedor_actual) # 'proveedor' para que coincida con el form

@main_bp.route('/proveedores/toggle_activo/<int:proveedor_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_proveedor(proveedor_id):
    """
    Cambia el estado 'activo' de un proveedor.
    """
    proveedor_actual = None
    db_conn = get_db()
    cursor_read = None
    cursor_update = None

    try:
        cursor_read = db_conn.cursor(dictionary=True)
        cursor_read.execute("SELECT id, nombre_empresa, activo FROM proveedores WHERE id = %s", (proveedor_id,))
        proveedor_actual = cursor_read.fetchone()

        if not proveedor_actual:
            flash(f'Proveedor con ID {proveedor_id} no encontrado.', 'warning')
            return redirect(url_for('main.listar_proveedores'))

        nuevo_estado_activo = not proveedor_actual['activo']
        
        if cursor_read: # Cerrar cursor de lectura antes de la escritura
            cursor_read.close()
            cursor_read = None 

        cursor_update = db_conn.cursor()
        sql_update = "UPDATE proveedores SET activo = %s WHERE id = %s"
        cursor_update.execute(sql_update, (nuevo_estado_activo, proveedor_id))
        db_conn.commit()
        
        mensaje_estado = "activado" if nuevo_estado_activo else "desactivado"
        flash(f'El proveedor "{proveedor_actual["nombre_empresa"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f'Error al cambiar el estado del proveedor: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_proveedor (ID: {proveedor_id}): {err}")
    finally:
        if cursor_read: # Por si falló antes de cerrarlo explícitamente
            cursor_read.close()
        if cursor_update:
            cursor_update.close()

    return redirect(url_for('main.listar_proveedores'))




@main_bp.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    """
    Maneja la visualización (GET) y el procesamiento completo (POST) de una nueva venta.
    Versión final, completa y unificada.
    """
    db_conn = get_db()
    # Constantes de negocio
    IGV_TASA = 0.18 
    PUNTOS_POR_SOL_GANADOS = 10 
    PUNTOS_POR_SOL_CANJE = 10   

    # --- INICIO PARTE 1: Carga de Datos para el Formulario ---
    listas_para_form = {
        'sucursales': [], 'clientes': [], 'empleados': [], 'servicios': [], 
        'productos': [], 'campanas_activas': [], 'planes_membresia_activos': [], 'estilos_catalogo': [],
        'metodos_pago': ["Efectivo", "Tarjeta Visa", "Tarjeta Mastercard", "Yape", "Plin", "Transferencia Bancaria", "Otro"],
        'tipos_comprobante': ["Nota de Venta", "Boleta Electrónica", "Factura Electrónica", "Otro"]
    }
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['sucursales'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, razon_social_nombres, apellidos FROM clientes ORDER BY razon_social_nombres, apellidos")
            listas_para_form['clientes'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            listas_para_form['empleados'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, precio, duracion_minutos, porcentaje_comision_extra FROM servicios WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['servicios'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT p.id, p.nombre, p.precio_venta, p.stock_actual, p.comision_vendedor_monto, m.nombre AS marca_nombre FROM productos p LEFT JOIN marcas m ON p.marca_id = m.id WHERE p.activo = TRUE ORDER BY p.nombre, m.nombre")
            listas_para_form['productos'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, tipo_regla, valor_regla FROM campanas WHERE activo = TRUE AND CURDATE() BETWEEN fecha_inicio AND fecha_fin ORDER BY nombre")
            listas_para_form['campanas_activas'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, precio, duracion_dias FROM membresia_planes WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['planes_membresia_activos'] = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM estilos WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['estilos_catalogo'] = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error fatal al cargar datos maestros para el formulario: {err_load}", "danger")
        return render_template('ventas/form_venta.html', es_nuevo=True, titulo_form="Error al Cargar Datos", **listas_para_form)
    # --- FIN PARTE 1 ---
 
    # --- INICIO PARTE 2: Lógica para el método POST ---
    if request.method == 'POST':
        try:
            # 2a. Recoger y Validar Datos iniciales
            errores = []
            sucursal_id = request.form.get('sucursal_id', type=int)
            empleado_id = request.form.get('empleado_id', type=int)
            fecha_venta_str = request.form.get('fecha_venta')
            cliente_receptor_id_str = request.form.get('cliente_receptor_id')
            cliente_facturacion_id_str = request.form.get('cliente_facturacion_id')
            campana_id = request.form.get('campana_id', type=int) or None
            items_json_str = request.form.get('items_json')
            pagos_json_str = request.form.get('pagos_json')
            descuento_aplicado_str = request.form.get('final_descuento_aplicado', '0.0')
            puntos_canjeados = request.form.get('puntos_canjeados', '0', type=int)
            reserva_id_origen = request.form.get('reserva_id_origen', type=int) or None
            tipo_comprobante = request.form.get('tipo_comprobante', '').strip() or None
            serie_comprobante = request.form.get('serie_comprobante', '').strip() or None
            notas_venta = request.form.get('notas_venta', '').strip() or None
            
            if not sucursal_id: errores.append("Debe seleccionar la sucursal.")
            if not empleado_id: errores.append("Debe seleccionar un colaborador.")
            if not fecha_venta_str: errores.append("La fecha de venta es obligatoria.")
            else: fecha_venta = datetime.fromisoformat(fecha_venta_str)
            
            cliente_receptor_id = int(cliente_receptor_id_str) if cliente_receptor_id_str and cliente_receptor_id_str != "0" else None
            cliente_facturacion_id = int(cliente_facturacion_id_str) if cliente_facturacion_id_str and cliente_facturacion_id_str.strip() else None
            if not cliente_facturacion_id:
                cliente_facturacion_id = cliente_receptor_id

            lista_items = json.loads(items_json_str or '[]')
            if not lista_items: errores.append("Debe añadir al menos un ítem a la venta.")
            
            # Separar ítems normales de la membresía vendida
            lista_items_normales = [item for item in lista_items if item.get('tipo_item') != 'Membresía']
            item_membresia_vendida = next((item for item in lista_items if item.get('tipo_item') == 'Membresía'), None)
            if item_membresia_vendida and not cliente_receptor_id:
                errores.append("Se debe seleccionar un cliente registrado para venderle una membresía.")

            # Recalcular total para validar si se requiere pago
            descuento_monto = float(descuento_aplicado_str if descuento_aplicado_str.strip() else 0.0)
            monto_venta_precalculado = sum(float(i.get('subtotal_item_neto', 0.0)) for i in lista_items) - descuento_monto
            
            lista_pagos = json.loads(pagos_json_str or '[]')
            if monto_venta_precalculado > 0 and not lista_pagos:
                errores.append("Debe registrar al menos un pago para ventas con un total mayor a cero.")

            if errores: raise ValueError("; ".join(errores))
            
            # --- 2b. Transacción de Escritura ---
            with db_conn.cursor(dictionary=True) as cursor:
                
                # Validar Stock
                for item in lista_items_normales:
                    if item.get('tipo_item') == 'Producto':
                        cursor.execute("SELECT nombre, stock_actual FROM productos WHERE id = %s FOR UPDATE", (item['item_id'],))
                        p_info = cursor.fetchone()
                        if not p_info: raise ValueError(f"Producto ID {item['item_id']} no encontrado.")
                        if p_info['stock_actual'] < int(item['cantidad']):
                            raise ValueError(f"Stock insuficiente para '{p_info['nombre']}'.")
                
                # Validar Puntos
                if puntos_canjeados > 0:
                    if not cliente_receptor_id: raise ValueError("No se pueden canjear puntos sin un cliente registrado.")
                    cursor.execute("SELECT puntos_fidelidad FROM clientes WHERE id = %s FOR UPDATE", (cliente_receptor_id,))
                    cliente_puntos = cursor.fetchone()
                    puntos_disponibles_db = cliente_puntos.get('puntos_fidelidad', 0) if cliente_puntos else 0
                    if not cliente_puntos or puntos_disponibles_db < puntos_canjeados:
                        raise ValueError(f"El cliente no tiene suficientes puntos. Disponibles: {puntos_disponibles_db}.")

                # Generar Correlativo
                numero_comprobante_final = None
                if tipo_comprobante and serie_comprobante:
                    cursor.execute("SELECT id, ultimo_numero_usado FROM comprobante_series WHERE sucursal_id = %s AND tipo_comprobante = %s AND serie = %s AND activo = TRUE FOR UPDATE", (sucursal_id, tipo_comprobante, serie_comprobante))
                    serie_info = cursor.fetchone()
                    if not serie_info: raise ValueError(f"La serie '{serie_comprobante}' no está configurada o activa.")
                    nuevo_numero = serie_info['ultimo_numero_usado'] + 1
                    numero_comprobante_final = str(nuevo_numero).zfill(8)
                    cursor.execute("UPDATE comprobante_series SET ultimo_numero_usado = %s WHERE id = %s", (nuevo_numero, serie_info['id']))
                
                # Recalcular Totales Finales
                recalculado_subtotal_servicios_con_igv = sum(float(i['subtotal_item_neto']) for i in lista_items_normales if i.get('tipo_item') == 'Servicio')
                recalculado_subtotal_productos_con_igv = sum(float(i['subtotal_item_neto']) for i in lista_items_normales if i.get('tipo_item') == 'Producto')
                subtotal_membresia = float(item_membresia_vendida['precio_unitario_venta']) if item_membresia_vendida else 0.0
                monto_final_venta = (recalculado_subtotal_servicios_con_igv + recalculado_subtotal_productos_con_igv + subtotal_membresia) - descuento_monto
                monto_impuestos = round(monto_final_venta - (monto_final_venta / (1 + IGV_TASA)), 2)
                estado_pago_servidor = request.form.get('estado_pago')

                # Insertar en 'ventas'
                sql_venta = "INSERT INTO ventas (sucursal_id, cliente_receptor_id, cliente_facturacion_id, empleado_id, fecha_venta, campana_id, subtotal_servicios, subtotal_productos, descuento_monto, monto_impuestos, monto_final_venta, estado_pago, estado_proceso, tipo_comprobante, serie_comprobante, numero_comprobante, notas_venta, reserva_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                val_venta = (sucursal_id, cliente_receptor_id, cliente_facturacion_id, empleado_id, fecha_venta, campana_id, recalculado_subtotal_servicios_con_igv + subtotal_membresia, recalculado_subtotal_productos_con_igv, descuento_monto, monto_impuestos, monto_final_venta, estado_pago_servidor, 'Facturada', tipo_comprobante, serie_comprobante, numero_comprobante_final, notas_venta, reserva_id_origen)
                cursor.execute(sql_venta, val_venta)
                venta_id = cursor.lastrowid
                
                # Bucle para ítems, comisiones y stock
                for item in lista_items_normales:
                    # 1. Definir variables al principio del bucle para claridad
                    item_servicio_id = item.get('item_id') if item.get('tipo_item') == 'Servicio' else None
                    item_producto_id = item.get('item_id') if item.get('tipo_item') == 'Producto' else None
                    subtotal_item = float(item['cantidad']) * float(item['precio_unitario_venta'])
             
                    es_trabajo_extra = bool(item.get('es__extra', False))

                    valor_produccion_item = subtotal_item # Por defecto, es el subtotal de venta
                    usado_como_beneficio = bool(item.get('usado_como_beneficio', False))
                    credito_id_usado = item.get('credito_id_usado')
                    
                    notas_del_item = item.get('notas_item', '').strip() or None
                    
                    
                    # 2. Determinar el valor de producción del ítem
                    valor_produccion_item = subtotal_item # Por defecto, es el subtotal de venta

                    if usado_como_beneficio and credito_id_usado:
                        # Si se usó un crédito, buscamos el precio definido en el paquete
                        cursor.execute("""
                            SELECT b.precio_en_paquete FROM membresia_plan_beneficios b
                            JOIN cliente_membresias cm ON b.plan_id = cm.plan_id
                            JOIN cliente_membresia_creditos c ON cm.id = c.cliente_membresia_id
                            WHERE c.id = %s
                        """, (credito_id_usado,))
                        beneficio_info = cursor.fetchone()
                        if beneficio_info and beneficio_info.get('precio_en_paquete') is not None:
                            valor_produccion_item = float(beneficio_info['precio_en_paquete'])
                        else:
                            # Si no se encuentra, usamos el precio normal del servicio (respaldo)
                            cursor.execute("SELECT precio FROM servicios WHERE id = %s", (item_servicio_id,))
                            servicio_info = cursor.fetchone()
                            valor_produccion_item = float(servicio_info['precio']) if servicio_info else 0.0
                    
                    # 3. Insertar el ítem en la tabla venta_items
                    sql_item = "INSERT INTO venta_items (venta_id, servicio_id, producto_id, descripcion_item_venta, cantidad, precio_unitario_venta, subtotal_item_bruto, subtotal_item_neto, valor_produccion, es_trabajo_extra, notas_item, usado_como_beneficio) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    val_item = (venta_id, item_servicio_id, item_producto_id, item['descripcion_item_venta'], int(item['cantidad']), float(item['precio_unitario_venta']), subtotal_item, subtotal_item, valor_produccion_item, bool(item.get('es_trabajo_extra', False)), item.get('notas_item'), usado_como_beneficio)
                    cursor.execute(sql_item, val_item)
                    venta_item_id = cursor.lastrowid

                    # 4. Descontar crédito de membresía si se usó
                    if usado_como_beneficio and credito_id_usado:
                        cursor.execute("UPDATE cliente_membresia_creditos SET cantidad_usada = cantidad_usada + 1 WHERE id = %s AND (cantidad_total - cantidad_usada) > 0", (credito_id_usado,))
                        if cursor.rowcount == 0: raise ValueError(f"El crédito para el servicio '{item['descripcion_item_venta']}' ya no estaba disponible.")
                    
                    # 5. Calcular y registrar comisión (solo si NO se usó un crédito)
                    monto_comision = 0.0
                    if not usado_como_beneficio:
                        if item_producto_id:
                            cursor.execute("SELECT comision_vendedor_monto FROM productos WHERE id = %s", (item_producto_id,))
                            producto_info = cursor.fetchone()
                            if producto_info and producto_info.get('comision_vendedor_monto'):
                                monto_comision = float(producto_info['comision_vendedor_monto']) * int(item['cantidad'])
                        elif es_trabajo_extra and item_servicio_id:
                            cursor.execute("SELECT porcentaje_comision_extra FROM servicios WHERE id = %s", (item_servicio_id,))
                            servicio_info = cursor.fetchone()
                            if servicio_info and servicio_info.get('porcentaje_comision_extra'):
                                monto_comision = subtotal_item * (float(servicio_info['porcentaje_comision_extra']) / 100)
                        
                        if monto_comision > 0:
                            sql_comision = "INSERT INTO comisiones (venta_item_id, colaborador_id, monto_comision, estado) VALUES (%s, %s, %s, 'Pendiente')"
                            val_comision = (venta_item_id, empleado_id, round(monto_comision, 2))
                            cursor.execute(sql_comision, val_comision)

                    # 6. Actualizar el stock si el ítem es un producto
                    if item_producto_id:
                        sql_stock = "UPDATE productos SET stock_actual = stock_actual - %s WHERE id = %s"
                        cursor.execute(sql_stock, (int(item['cantidad']), item_producto_id))
                
                        
                # Activar membresía si se vendió
                if item_membresia_vendida and cliente_receptor_id:
                    plan_id = int(item_membresia_vendida['item_id'])
                    cursor.execute("SELECT duracion_dias FROM membresia_planes WHERE id = %s", (plan_id,))
                    plan_info = cursor.fetchone()
                    if not plan_info: raise ValueError("El plan de membresía vendido no es válido.")
                    duracion = timedelta(days=plan_info['duracion_dias'])
                    sql_membresia = "INSERT INTO cliente_membresias (cliente_id, plan_id, venta_id, fecha_inicio, fecha_fin, estado) VALUES (%s, %s, %s, %s, %s, 'Activa')"
                    cursor.execute(sql_membresia, (cliente_receptor_id, plan_id, venta_id, date.today(), date.today() + duracion))
                    cliente_membresia_id = cursor.lastrowid
                    cursor.execute("SELECT servicio_id, cantidad_incluida FROM membresia_plan_beneficios WHERE plan_id = %s", (plan_id,))
                    beneficios = cursor.fetchall()
                    if beneficios:
                        sql_credito = "INSERT INTO cliente_membresia_creditos (cliente_membresia_id, servicio_id, cantidad_total) VALUES (%s, %s, %s)"
                        valores_creditos = [(cliente_membresia_id, b['servicio_id'], b['cantidad_incluida']) for b in beneficios]
                        cursor.executemany(sql_credito, valores_creditos)

                # Insertar Pagos
                for pago in lista_pagos:
                    cursor.execute("INSERT INTO venta_pagos (venta_id, metodo_pago, monto, referencia_pago) VALUES (%s, %s, %s, %s)", (venta_id, pago['metodo_pago'], float(pago['monto']), pago.get('referencia_pago')))

                # Lógica de Puntos
                if puntos_canjeados > 0 and cliente_receptor_id:
                    cursor.execute("UPDATE clientes SET puntos_fidelidad = puntos_fidelidad - %s WHERE id = %s", (puntos_canjeados, cliente_receptor_id))
                    cursor.execute("INSERT INTO puntos_log (cliente_id, venta_id, puntos_cambio, tipo_transaccion, descripcion) VALUES (%s, %s, %s, 'Canje en Venta', %s)", (cliente_receptor_id, venta_id, -puntos_canjeados, f"Descuento de S/ {descuento_monto:.2f}"))
                if estado_pago_servidor == 'Pagado' and cliente_receptor_id:
                    monto_base_puntos = recalculado_subtotal_servicios_con_igv
                    if monto_base_puntos > 0:
                        puntos_base = math.floor(monto_base_puntos / PUNTOS_POR_SOL_GANADOS)
                        puntos_ganados = puntos_base
                        # ... (lógica de campañas para multiplicar puntos) ...
                        if puntos_ganados > 0:
                            cursor.execute("UPDATE clientes SET puntos_fidelidad = puntos_fidelidad + %s WHERE id = %s", (puntos_ganados, cliente_receptor_id))
                            cursor.execute("INSERT INTO puntos_log (cliente_id, venta_id, puntos_cambio, tipo_transaccion) VALUES (%s, %s, %s, 'Acumulación por Venta')", (cliente_receptor_id, venta_id, puntos_ganados))
            
            db_conn.commit()
            flash(f"Venta #{venta_id} registrada exitosamente.", "success")
            return redirect(url_for('main.nueva_venta')) 

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"No se pudo guardar la venta. Error: {str(e)}", "warning")
            current_app.logger.error(f"Error procesando venta: {e}")
            return render_template('ventas/form_venta.html', form_data=request.form, es_nuevo=True, titulo_form="Registrar Nueva Venta (Corregir Errores)", **listas_para_form)
    # --- FIN PARTE 2 ---
    
    # --- INICIO PARTE 3: Lógica para el método GET ---
    # Este bloque se ejecuta si la petición NO es POST, es decir, al cargar la página por primera vez
    # o al ser redirigido desde otra página.
    
    # Preparar variables para pre-llenar el formulario
    
    
    prefill_data = {}
    prefill_items_json = '[]'
    comanda_origen_id = request.args.get('comanda_id', type=int)
    
    if comanda_origen_id:
        try:
            with db_conn.cursor(dictionary=True) as cursor:
                cursor.execute("SELECT * FROM ventas WHERE id = %s AND estado_proceso = 'En Comanda'", (comanda_origen_id,))
                comanda_data = cursor.fetchone()

                if comanda_data:
                    # Preparar los datos de la cabecera para los campos del formulario
                    prefill_data['sucursal_id'] = comanda_data['sucursal_id']
                    prefill_data['cliente_receptor_id'] = comanda_data['cliente_receptor_id']
                    prefill_data['empleado_id'] = comanda_data['empleado_id']
                    
                    cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (comanda_origen_id,))
                    items_de_comanda = cursor.fetchall()
                    
                    items_para_js = []
                    for item in items_de_comanda:
                        items_para_js.append({
                            "tipo_item": "Servicio" if item['servicio_id'] else "Producto",
                            "item_id": str(item['servicio_id'] or item['producto_id']),
                            "descripcion_item_venta": item['descripcion_item_venta'],
                            "cantidad": item['cantidad'],
                            "precio_unitario_venta": float(item['precio_unitario_venta']),
                            "es_trabajo_extra": bool(item['es_trabajo_extra']),
                            "notas_item": item.get('notas_item', ''),
                            "subtotal_item_neto": float(item['subtotal_item_neto']),
                            "subtotal_item_bruto": float(item['subtotal_item_bruto'])
                        })
                    prefill_items_json = json.dumps(items_para_js)
                    flash(f"Cargando Comanda #{comanda_origen_id} para finalizar la venta.", "info")
                else:
                    flash(f"La comanda #{comanda_origen_id} no fue encontrada o ya fue procesada.", "warning")
                    comanda_origen_id = None
        except mysql.connector.Error as err:
            flash(f"Error al cargar datos de la comanda: {err}", "danger")
    
            
    reserva_id_origen = request.args.get('reserva_id', type=int)
    
    if reserva_id_origen:
        try:
            with db_conn.cursor(dictionary=True) as cursor:
                # Obtener datos de la reserva
                cursor.execute("""
                    SELECT r.cliente_id, r.empleado_id, r.sucursal_id, r.servicio_id, s.nombre as servicio_nombre, s.precio as servicio_precio 
                    FROM reservas r JOIN servicios s ON r.servicio_id = s.id 
                    WHERE r.id = %s
                """, (reserva_id_origen,))
                reserva_data = cursor.fetchone()
                
                if reserva_data:
                    prefill_data['cliente_receptor_id'] = reserva_data['cliente_id']
                    prefill_data['empleado_id'] = reserva_data['empleado_id']
                    prefill_data['sucursal_id'] = reserva_data['sucursal_id']
                    
                    # Crear el ítem del servicio para la tabla de venta
                    item_servicio = {
                        "tipo_item": "Servicio",
                        "item_id": str(reserva_data['servicio_id']),
                        "descripcion_item_venta": reserva_data['servicio_nombre'],
                        "cantidad": 1,
                        "precio_unitario_venta": float(reserva_data['servicio_precio']),
                        "es_trabajo_extra": False,
                        "notas_item": "",
                        "subtotal_item_neto": float(reserva_data['servicio_precio']),
                        "subtotal_item_bruto": float(reserva_data['servicio_precio'])
                    }
                    prefill_items_json = json.dumps([item_servicio]) # Convertir a string JSON
                    flash(f"Cargando datos de la Reserva #{reserva_id_origen}.", "info")

        except mysql.connector.Error as err:
            flash(f"Error al cargar datos de la reserva: {err}", "danger")

    return render_template('ventas/form_venta.html',
                           es_nuevo=True, 
                           titulo_form="Registrar Venta",
                           action_url=url_for('main.nueva_venta'),
                           prefill_data=prefill_data,
                           prefill_items_json=prefill_items_json,
                           comanda_origen_id=comanda_origen_id,
                           **listas_para_form)
    # --- FIN PARTE 3 ---
    
@main_bp.route('/ventas/editar/<int:venta_id>', methods=['GET', 'POST'])
@login_required
def editar_venta(venta_id):
    """
    Maneja la visualización (GET) y el procesamiento (POST) 
    del formulario para editar una venta existente.
    """
    db_conn = get_db()
    
    # --- 1. Obtener los datos de la venta que se está editando ---
    # Esto se hace fuera del bloque POST/GET porque se necesita en ambos casos
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM ventas WHERE id = %s", (venta_id,))
            venta_actual = cursor.fetchone()
    except mysql.connector.Error as err_fetch:
        flash(f"Error de base de datos al buscar la venta: {err_fetch}", "danger")
        return redirect(url_for('main.listar_ventas'))

    if not venta_actual:
        flash(f"Venta con ID {venta_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_ventas'))

    # --- 2. Cargar datos maestros para los menús desplegables ---
    # Esto también se necesita en ambos casos (GET y re-renderizado en POST con error)
    sucursales_activas, clientes_todos, empleados_activos = [], [], []
    metodos_pago_opciones = ["Efectivo", "Tarjeta Visa", "Tarjeta Mastercard", "Yape", "Plin", "Transferencia Bancaria", "Otro"]
    tipos_comprobante_opciones = ["Nota de Venta", "Boleta Electrónica", "Factura Electrónica", "Otro"]
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM clientes ORDER BY apellidos, nombres")
            clientes_todos = cursor.fetchall()
            clientes_todos.insert(0, {"id": "0", "nombres": "Cliente", "apellidos": "Varios"})
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            empleados_activos = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar datos maestros para el formulario: {err_load}", "danger")
        current_app.logger.error(f"Error DB cargando dropdown data en editar_venta: {err_load}")


    # --- 3. Lógica POST (cuando se guarda el formulario de edición) ---
    if request.method == 'POST':
        cursor_update = None
        try:
            # Recoger datos del formulario
            sucursal_id = request.form.get('sucursal_id', type=int)
            cliente_id_str = request.form.get('cliente_id')
            empleado_id = request.form.get('empleado_id', type=int)
            fecha_venta_str = request.form.get('fecha_venta')
            tipo_comprobante = request.form.get('tipo_comprobante', '').strip() or None
            notas_venta = request.form.get('notas_venta', '').strip() or None
            pagos_json_str = request.form.get('pagos_json')
            
            # Validar datos básicos
            errores = []
            if not sucursal_id: errores.append("Sucursal es obligatoria.")
            if not empleado_id: errores.append("Colaborador es obligatorio.")
            if not fecha_venta_str: errores.append("Fecha de venta es obligatoria.")
            
            cliente_id = int(cliente_id_str) if cliente_id_str and cliente_id_str != "0" else None
            fecha_venta = datetime.fromisoformat(fecha_venta_str)
            
            lista_pagos_nuevos = json.loads(pagos_json_str) if pagos_json_str else []
            if not lista_pagos_nuevos:
                errores.append("Debe haber al menos un método de pago registrado.")

            if errores:
                raise ValueError("; ".join(errores))

            # Calcular nuevo estado de pago
            total_pagado_nuevo = sum(float(p['monto']) for p in lista_pagos_nuevos)
            monto_final_venta = float(venta_actual['monto_final_venta'])
            
            estado_pago_nuevo = "Pendiente de Pago"
            if abs(total_pagado_nuevo - monto_final_venta) < 0.01 or total_pagado_nuevo > monto_final_venta:
                estado_pago_nuevo = "Pagado"
            elif total_pagado_nuevo > 0:
                estado_pago_nuevo = "Parcialmente Pagado"
            
            # Iniciar Transacción de forma implícita (NO se usa start_transaction())
            cursor_update = db_conn.cursor()

            # Actualizar la cabecera de la venta
            sql_update_venta = """UPDATE ventas SET 
                                    sucursal_id = %s, cliente_id = %s, empleado_id = %s, fecha_venta = %s,
                                    tipo_comprobante = %s, notas_venta = %s, estado_pago = %s
                                  WHERE id = %s"""
            val_update_venta = (sucursal_id, cliente_id, empleado_id, fecha_venta, 
                                tipo_comprobante, notas_venta, 
                                estado_pago_nuevo, venta_id)
            cursor_update.execute(sql_update_venta, val_update_venta)

            # Borrar los pagos antiguos y guardar los nuevos
            cursor_update.execute("DELETE FROM venta_pagos WHERE venta_id = %s", (venta_id,))
            for pago in lista_pagos_nuevos:
                sql_pago = "INSERT INTO venta_pagos (venta_id, metodo_pago, monto, referencia_pago) VALUES (%s, %s, %s, %s)"
                val_pago = (venta_id, pago['metodo_pago'], float(pago['monto']), (pago.get('referencia_pago') or None))
                cursor_update.execute(sql_pago, val_pago)
            
            # Ajustar puntos de fidelidad si el estado de 'Pagado' cambió
            estado_pago_original = venta_actual['estado_pago']
            if estado_pago_original != estado_pago_nuevo and venta_actual.get('cliente_id'):
                puntos_a_ajustar = math.floor(monto_final_venta / 10)
                if puntos_a_ajustar > 0:
                    if estado_pago_nuevo == 'Pagado':
                        sql_puntos = "UPDATE clientes SET puntos_fidelidad = puntos_fidelidad + %s WHERE id = %s"
                        cursor_update.execute(sql_puntos, (puntos_a_ajustar, venta_actual['cliente_id']))
                    elif estado_pago_original == 'Pagado':
                        sql_puntos = "UPDATE clientes SET puntos_fidelidad = GREATEST(0, puntos_fidelidad - %s) WHERE id = %s"
                        cursor_update.execute(sql_puntos, (puntos_a_ajustar, venta_actual['cliente_id']))

            db_conn.commit()
            flash("Venta actualizada exitosamente.", "success")
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: 
                db_conn.rollback()
            # Flashear el error específico que ocurrió
            flash(f"No se pudo actualizar la venta. Error: {str(e)}", "danger")
            current_app.logger.error(f"Error procesando edición de venta: {e}")
            # La ejecución continuará y re-renderizará el formulario abajo
            
    # --- Lógica GET (o si el POST falló) ---
    # Obtener ítems y pagos actuales para mostrar en el formulario
    items_actuales, pagos_actuales = [], []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("""
                SELECT vi.*, p.nombre as producto_nombre, s.nombre as servicio_nombre 
                FROM venta_items vi 
                LEFT JOIN productos p ON vi.producto_id = p.id 
                LEFT JOIN servicios s ON vi.servicio_id = s.id 
                WHERE vi.venta_id = %s ORDER BY vi.id""", (venta_id,))
            items_actuales = cursor.fetchall()

            cursor.execute("SELECT * FROM venta_pagos WHERE venta_id = %s ORDER BY id", (venta_id,))
            pagos_actuales = cursor.fetchall()
    except mysql.connector.Error as err_fetch:
        flash(f"Error al obtener los detalles de la venta a editar: {err_fetch}", "danger")

    # Formatear la fecha para el input
    if venta_actual.get('fecha_venta') and isinstance(venta_actual['fecha_venta'], datetime):
        venta_actual['fecha_venta_str'] = venta_actual['fecha_venta'].strftime('%Y-%m-%dT%H:%M')
    
    # Si venimos de un POST fallido, form_data será request.form. Si es GET, será None.
    form_data_source = request.form if request.method == 'POST' else None
    # Si venimos de un POST fallido, usar el JSON de pagos que el usuario intentó guardar
    pagos_json_para_plantilla = request.form.get('pagos_json', '[]') if request.method == 'POST' else json.dumps(pagos_actuales, default=str)

    return render_template('ventas/form_editar_venta.html',
                           titulo_form=f"Editar Venta #{venta_id}",
                           action_url=url_for('main.editar_venta', venta_id=venta_id),
                           venta=venta_actual,
                           items_venta=items_actuales,
                           pagos_venta_json=pagos_json_para_plantilla,
                           form_data=form_data_source,
                           # Pasar listas para los desplegables
                           sucursales=sucursales_activas,
                           clientes=clientes_todos,
                           empleados=empleados_activos,
                           metodos_pago=metodos_pago_opciones,
                           tipos_comprobante=tipos_comprobante_opciones
                           )


@main_bp.route('/ventas/anular/<int:venta_id>', methods=['POST'])
@login_required
@admin_required
def anular_venta(venta_id):
    """
    Anula una venta: cambia el estado, revierte el stock de productos
    y revierte los puntos de fidelidad otorgados.
    Versión final con manejo de transacción corregido.
    """
    db_conn = get_db()
    
    try:
        # Usamos 'with' para que el cursor se cierre automáticamente
        with db_conn.cursor(dictionary=True) as cursor:
            # NO hay 'start_transaction()'. La transacción comenzará con el 'FOR UPDATE'.
            
            # 1. Obtener datos de la venta para validar y bloquear la fila
            cursor.execute("SELECT * FROM ventas WHERE id = %s FOR UPDATE", (venta_id,))
            venta = cursor.fetchone()

            if not venta:
                raise ValueError("Venta no encontrada.")
            
            if venta['estado_proceso'] == 'Anulada':
                flash(f"La venta #{venta_id} ya se encuentra anulada.", "info")
                db_conn.rollback() # Cancelar la transacción iniciada por el 'FOR UPDATE'
                return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

            # 2. Obtener los ítems de la venta para revertir stock
            cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,))
            items_de_la_venta = cursor.fetchall()

            for item in items_de_la_venta:
                if item['producto_id'] is not None:
                    # Revertir stock: sumar la cantidad de vuelta al producto
                    cursor.execute("UPDATE productos SET stock_actual = stock_actual + %s WHERE id = %s", 
                                   (item['cantidad'], item['producto_id']))

            # 3. Revertir puntos de fidelidad si se otorgaron
            cliente_id_para_puntos = venta.get('cliente_receptor_id')
            if venta['estado_pago'] == 'Pagado' and cliente_id_para_puntos:
                monto_base_puntos = float(venta.get('subtotal_servicios', 0.0))
                puntos_otorgados = math.floor(monto_base_puntos / 10)
                
                if puntos_otorgados > 0:
                    cursor.execute("UPDATE clientes SET puntos_fidelidad = GREATEST(0, puntos_fidelidad - %s) WHERE id = %s",
                                   (puntos_otorgados, cliente_id_para_puntos))
                    cursor.execute("INSERT INTO puntos_log (cliente_id, venta_id, puntos_cambio, tipo_transaccion, descripcion) VALUES (%s, %s, %s, 'Reversión por Anulación', %s)",
                                   (cliente_id_para_puntos, venta_id, -puntos_otorgados, f"Anulación de Venta #{venta_id}"))

            # 4. Actualizar el estado de la venta a 'Anulado'
            cursor.execute("UPDATE ventas SET estado_proceso = 'Anulada', estado_pago = 'Anulado' WHERE id = %s", (venta_id,))

        # Si el bloque 'with' termina sin errores, se guardan todos los cambios
        db_conn.commit()
        flash(f"Venta #{venta_id} anulada exitosamente. El stock y los puntos han sido revertidos.", "success")

    except (ValueError, mysql.connector.Error, Exception) as e:
        if db_conn and db_conn.in_transaction:
            db_conn.rollback()
        flash(f"Ocurrió un error inesperado al anular la venta: {e}", "danger")
        current_app.logger.error(f"Error en anular_venta (ID: {venta_id}): {e}")

    return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

@main_bp.route('/ventas/detalle/<int:venta_id>')
@login_required
@admin_required # O el permiso correspondiente
def ver_detalle_venta(venta_id):
    """
    Muestra el detalle completo de una venta.
    Versión corregida con el alias 'venta_id'.
    """
    db_conn = get_db()
    venta_actual, items_actuales, pagos_actuales = None, [], []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # --- CORRECCIÓN AQUÍ: Se añadió el alias 'AS venta_id' a la columna v.id ---
            sql_cabecera = """
                SELECT 
                    v.id AS venta_id, v.*,
                    s.nombre AS sucursal_nombre,
                    e.nombre_display AS colaborador_nombre,
                    COALESCE(CONCAT(c_receptor.razon_social_nombres, ' ', c_receptor.apellidos), 'Cliente Varios') AS cliente_receptor_nombre,
                    COALESCE(CONCAT(c_factura.razon_social_nombres, ' ', c_factura.apellidos), '-') AS cliente_factura_nombre
                FROM ventas v
                JOIN sucursales s ON v.sucursal_id = s.id
                JOIN empleados e ON v.empleado_id = e.id
                LEFT JOIN clientes c_receptor ON v.cliente_receptor_id = c_receptor.id
                LEFT JOIN clientes c_factura ON v.cliente_facturacion_id = c_factura.id
                WHERE v.id = %s
            """
            cursor.execute(sql_cabecera, (venta_id,))
            venta_actual = cursor.fetchone()
            
            if not venta_actual:
                flash(f"Venta con ID {venta_id} no encontrada.", "warning")
                return redirect(url_for('main.listar_ventas'))

            cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s ORDER BY id", (venta_id,))
            items_actuales = cursor.fetchall()

            cursor.execute("SELECT * FROM venta_pagos WHERE venta_id = %s ORDER BY id", (venta_id,))
            pagos_actuales = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al cargar el detalle de la venta: {err}", "danger")
        return redirect(url_for('main.listar_ventas'))

    return render_template('ventas/ver_venta.html',
                           venta=venta_actual,
                           items=items_actuales,
                           pagos=pagos_actuales,
                           titulo_pagina=f"Detalle de Venta #{venta_actual['serie_comprobante']}-{venta_actual['numero_comprobante']}")
    
@main_bp.route('/ventas/imprimir/<int:venta_id>')
@login_required
def imprimir_ticket_venta(venta_id):
    """
    Prepara los datos y muestra una vista de ticket para imprimir.
    """
    db_conn = get_db()
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # 1. Obtener la cabecera de la venta y datos relacionados
            sql_cabecera = """
                SELECT 
                    v.*,
                    s.nombre AS sucursal_nombre, s.direccion AS sucursal_direccion, s.telefono AS sucursal_telefono,
                    e.nombre_display AS colaborador_nombre_display,
                    CONCAT(cl.nombres, ' ', cl.apellidos) AS cliente_nombre_completo
                FROM ventas v
                JOIN sucursales s ON v.sucursal_id = s.id
                JOIN empleados e ON v.empleado_id = e.id
                LEFT JOIN clientes cl ON v.cliente_id = cl.id
                WHERE v.id = %s
            """
            cursor.execute(sql_cabecera, (venta_id,))
            venta_actual = cursor.fetchone()
            
            if not venta_actual:
                flash(f"Venta con ID {venta_id} no encontrada.", "warning")
                return redirect(url_for('main.listar_ventas'))

            # 2. Obtener los ítems de la venta
            cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s ORDER BY id", (venta_id,))
            items_actuales = cursor.fetchall()

            # 3. Obtener los pagos de la venta
            cursor.execute("SELECT * FROM venta_pagos WHERE venta_id = %s ORDER BY id", (venta_id,))
            pagos_actuales = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al generar el ticket de venta: {err}", "danger")
        return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

    return render_template('ventas/ticket_venta.html',
                           venta=venta_actual,
                           items=items_actuales,
                           pagos=pagos_actuales)

    
@main_bp.route('/ventas')
@login_required
@admin_required # O el permiso que hayas definido
def listar_ventas():
    """
    Muestra una lista de todas las ventas registradas.
    Versión corregida con el alias 'venta_id' verificado.
    """
    db_conn = get_db()
    lista_de_ventas = []
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # --- CORRECCIÓN CLAVE ---
            # Nos aseguramos de que la columna v.id se renombre a 'venta_id'
            sql = """
                SELECT 
                    v.id AS venta_id, 
                    v.fecha_venta, 
                    v.monto_final_venta, 
                    v.estado_pago,
                    v.serie_comprobante, 
                    v.numero_comprobante,
                    e.nombre_display AS empleado_nombre,
                    COALESCE(CONCAT(c.razon_social_nombres, ' ', c.apellidos), 'Cliente Varios') AS cliente_nombre
                FROM ventas v
                JOIN empleados e ON v.empleado_id = e.id
                LEFT JOIN clientes c ON v.cliente_receptor_id = c.id
                ORDER BY v.fecha_venta DESC
            """
            cursor.execute(sql)
            lista_de_ventas = cursor.fetchall()
            
    except mysql.connector.Error as err:
        flash(f"Error al acceder al historial de ventas: {err}", "danger")
        current_app.logger.error(f"Error en listar_ventas: {err}")
        
    return render_template('ventas/lista_ventas.html', 
                           ventas=lista_de_ventas,
                           titulo_pagina="Historial de Ventas")
    
    
@main_bp.route('/configuracion/sucursales')
@login_required
@admin_required
def listar_sucursales():
    """
    Muestra la lista de todas las sucursales del negocio.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM sucursales ORDER BY nombre")
        lista_de_sucursales = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las sucursales: {err}", "danger")
        current_app.logger.error(f"Error en listar_sucursales: {err}")
        lista_de_sucursales = []
        
    return render_template('configuracion/lista_sucursales.html', 
                           sucursales=lista_de_sucursales,
                           titulo_pagina="Sucursales")

@main_bp.route('/configuracion/sucursales/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_sucursal():
    """
    Muestra el formulario para registrar una nueva sucursal (GET)
    y procesa la creación de la sucursal (POST).
    """
    form_titulo = "Registrar Nueva Sucursal"
    action_url_form = url_for('main.nueva_sucursal')

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        direccion = request.form.get('direccion', '').strip()
        ciudad = request.form.get('ciudad', '').strip()
        telefono = request.form.get('telefono', '').strip()
        email = request.form.get('email', '').strip()
        codigo_sunat = request.form.get('codigo_establecimiento_sunat', '').strip()
        activo = 'activo' in request.form

        if not nombre:
            flash('El nombre de la sucursal es obligatorio.', 'warning')
            # Volver a renderizar con los datos ingresados
            return render_template('configuracion/form_sucursal.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

        cursor_insert = None
        try:
            db = get_db()
            cursor_insert = db.cursor()
            sql = """INSERT INTO sucursales 
                        (nombre, direccion, ciudad, telefono, email, codigo_establecimiento_sunat, activo) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s)"""
            val = (nombre, 
                   (direccion if direccion else None), 
                   (ciudad if ciudad else None), 
                   (telefono if telefono else None), 
                   (email if email else None), 
                   (codigo_sunat if codigo_sunat else None), 
                   activo)
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Sucursal "{nombre}" registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_sucursales'))
        except mysql.connector.Error as err:
            db.rollback()
            if err.errno == 1062: # Error de entrada duplicada (nombre UNIQUE)
                flash(f'Error: Ya existe una sucursal con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la sucursal: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_sucursal (POST): {err}")
            return render_template('configuracion/form_sucursal.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('configuracion/form_sucursal.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form)

@main_bp.route('/configuracion/sucursales/editar/<int:sucursal_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_sucursal(sucursal_id):
    """
    Muestra el formulario para editar una sucursal existente (GET)
    y procesa la actualización (POST).
    """
    db_conn = get_db()
    cursor = None 

    # Obtener la sucursal actual para editar
    sucursal_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM sucursales WHERE id = %s", (sucursal_id,))
        sucursal_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la sucursal: {err}", "danger")
        current_app.logger.error(f"Error DB buscando sucursal en editar (ID: {sucursal_id}): {err}")
        return redirect(url_for('main.listar_sucursales'))
    finally:
        if cursor: 
            cursor.close()
            cursor = None 

    if not sucursal_actual:
        flash(f"Sucursal con ID {sucursal_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_sucursales'))

    form_titulo = f"Editar Sucursal: {sucursal_actual.get('nombre', '')}"
    action_url_form = url_for('main.editar_sucursal', sucursal_id=sucursal_id)

    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre')
        direccion_nueva = request.form.get('direccion', '').strip()
        ciudad_nueva = request.form.get('ciudad', '').strip()
        telefono_nuevo = request.form.get('telefono', '').strip()
        email_nuevo = request.form.get('email', '').strip()
        codigo_sunat_nuevo = request.form.get('codigo_establecimiento_sunat', '').strip()
        activo_nuevo = 'activo' in request.form
        
        errores = []
        if not nombre_nuevo:
            errores.append('El nombre de la sucursal es obligatorio.')

        # Validar unicidad del nombre si ha cambiado
        if nombre_nuevo and nombre_nuevo.lower() != sucursal_actual.get('nombre', '').lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM sucursales WHERE nombre = %s AND id != %s", (nombre_nuevo, sucursal_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra sucursal con el nombre "{nombre_nuevo}".')
            except mysql.connector.Error as err_check:
                current_app.logger.error(f"Error DB verificando nombre sucursal: {err_check}")
                errores.append("Error al verificar la disponibilidad del nombre de la sucursal.")
            finally:
                if cursor: cursor.close(); cursor = None
        
        if errores:
            for error_msg in errores:
                flash(error_msg, 'warning')
            return render_template('configuracion/form_sucursal.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   sucursal=sucursal_actual, 
                                   form_data=request.form)
        else:
            # Actualizar la sucursal en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = """UPDATE sucursales SET 
                                    nombre = %s, direccion = %s, ciudad = %s, telefono = %s, 
                                    email = %s, codigo_establecimiento_sunat = %s, activo = %s
                                WHERE id = %s"""
                val_update = (nombre_nuevo, 
                              (direccion_nueva if direccion_nueva else None),
                              (ciudad_nueva if ciudad_nueva else None),
                              (telefono_nuevo if telefono_nuevo else None),
                              (email_nuevo if email_nuevo else None),
                              (codigo_sunat_nuevo if codigo_sunat_nuevo else None),
                              activo_nuevo, sucursal_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'Sucursal "{nombre_nuevo}" actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_sucursales'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                if err_upd.errno == 1062:
                     flash(f'Error: Ya existe una sucursal con el nombre "{nombre_nuevo}".', 'danger')
                else:
                    flash(f"Error al actualizar la sucursal: {err_upd}", 'danger')
                current_app.logger.error(f"Error DB en POST editar_sucursal (ID: {sucursal_id}): {err_upd}")
            finally:
                if cursor: cursor.close()
            
            return render_template('configuracion/form_sucursal.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   sucursal=sucursal_actual,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales de la sucursal
    return render_template('configuracion/form_sucursal.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           sucursal=sucursal_actual) # 'sucursal' para que coincida con el form
    
@main_bp.route('/configuracion/sucursales/toggle_activo/<int:sucursal_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_sucursal(sucursal_id):
    """
    Cambia el estado 'activo' de una sucursal.
    """
    sucursal_actual = None
    db_conn = get_db()
    cursor = None # Usaremos este cursor para leer y luego para escribir

    try:
        cursor = db_conn.cursor(dictionary=True)
        # Obtener el estado actual de la sucursal
        cursor.execute("SELECT id, nombre, activo FROM sucursales WHERE id = %s", (sucursal_id,))
        sucursal_actual = cursor.fetchone()

        if not sucursal_actual:
            flash(f'Sucursal con ID {sucursal_id} no encontrada.', 'warning')
            return redirect(url_for('main.listar_sucursales'))

        nuevo_estado_activo = not sucursal_actual['activo']
        
        # Actualizar el estado en la base de datos
        cursor.execute("UPDATE sucursales SET activo = %s WHERE id = %s", (nuevo_estado_activo, sucursal_id))
        db_conn.commit()
        
        mensaje_estado = "activada" if nuevo_estado_activo else "desactivada"
        flash(f'La sucursal "{sucursal_actual["nombre"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f'Error al cambiar el estado de la sucursal: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_sucursal (ID: {sucursal_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_sucursales'))    

@main_bp.route('/configuracion/series')
@login_required
@admin_required
def listar_series():
    """
    Muestra la lista de todas las series de comprobantes configuradas,
    incluyendo la sucursal a la que pertenecen.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Consulta actualizada con JOIN a la tabla 'sucursales'
        sql = """
            SELECT 
                cs.id, cs.tipo_comprobante, cs.serie, 
                cs.ultimo_numero_usado, cs.activo,
                s.nombre AS sucursal_nombre 
            FROM comprobante_series cs
            JOIN sucursales s ON cs.sucursal_id = s.id
            ORDER BY s.nombre, cs.tipo_comprobante, cs.serie
        """
        cursor.execute(sql)
        lista_de_series = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a la configuración de series: {err}", "danger")
        current_app.logger.error(f"Error en listar_series: {err}")
        lista_de_series = []
        
    return render_template('configuracion/lista_series.html', 
                           series=lista_de_series,
                           titulo_pagina="Series y Correlativos")

@main_bp.route('/configuracion/series/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_serie():
    """
    Muestra el formulario para registrar una nueva serie (GET)
    y procesa la creación de la serie (POST), asociándola a una sucursal.
    """
    db_conn = get_db()
    cursor = None
    
    # Cargar sucursales activas para el dropdown
    sucursales_activas = []
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar sucursales: {err_load}", "danger")
    finally:
        if cursor: cursor.close()

    form_titulo = "Registrar Nueva Serie de Comprobante"
    action_url_form = url_for('main.nueva_serie')
    tipos_comprobante_opciones = ["Nota de Venta", "Boleta Electrónica", "Factura Electrónica", "Otro"]

    if request.method == 'POST':
        sucursal_id_str = request.form.get('sucursal_id') # <<< NUEVO
        tipo_comprobante = request.form.get('tipo_comprobante')
        serie = request.form.get('serie', '').strip().upper()
        ultimo_numero_usado_str = request.form.get('ultimo_numero_usado', '0')
        activo = 'activo' in request.form

        errores = []
        sucursal_id = None
        if not sucursal_id_str: # Ahora es obligatorio
            errores.append("Debe seleccionar una sucursal.")
        else:
            try: sucursal_id = int(sucursal_id_str)
            except ValueError: errores.append("Sucursal seleccionada inválida.")
        
        if not tipo_comprobante:
            errores.append("Debe seleccionar un tipo de comprobante.")
        if not serie:
            errores.append("El código de la serie es obligatorio (ej. B001, F001).")
        
        ultimo_numero_usado = 0
        try:
            ultimo_numero_usado = int(ultimo_numero_usado_str)
            if ultimo_numero_usado < 0:
                errores.append("El último número usado no puede ser negativo.")
        except (ValueError, TypeError):
            errores.append("El último número usado debe ser un número entero.")

        if errores:
            for error in errores:
                flash(error, 'warning')
            return render_template('configuracion/form_serie.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   tipos_comprobante=tipos_comprobante_opciones,
                                   sucursales=sucursales_activas) # Pasar sucursales al re-renderizar

        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            # La consulta INSERT ahora incluye sucursal_id
            sql = "INSERT INTO comprobante_series (sucursal_id, tipo_comprobante, serie, ultimo_numero_usado, activo) VALUES (%s, %s, %s, %s, %s)"
            val = (sucursal_id, tipo_comprobante, serie, ultimo_numero_usado, activo)
            cursor_insert.execute(sql, val)
            db_conn.commit()
            flash(f'La serie "{serie}" para "{tipo_comprobante}" ha sido registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_series'))
        except mysql.connector.Error as err:
            db_conn.rollback()
            if err.errno == 1062: # Error de uq_sucursal_tipo_serie
                flash(f'Error: La combinación de sucursal, tipo "{tipo_comprobante}" y serie "{serie}" ya existe.', 'danger')
            else:
                flash(f'Error al registrar la serie: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_serie (POST): {err}")
            return render_template('configuracion/form_serie.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   tipos_comprobante=tipos_comprobante_opciones,
                                   sucursales=sucursales_activas)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('configuracion/form_serie.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           tipos_comprobante=tipos_comprobante_opciones,
                           sucursales=sucursales_activas) # Pasar sucursales

    # app/routes.py
# ... (tus importaciones y rutas existentes, incluyendo nueva_serie) ...

@main_bp.route('/configuracion/series/editar/<int:serie_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_serie(serie_id):
    """
    Muestra el formulario para editar una serie existente (GET)
    y procesa la actualización (POST).
    """
    db_conn = get_db()
    cursor = None 

    # Obtener la serie actual para editar
    serie_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM comprobante_series WHERE id = %s", (serie_id,))
        serie_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la serie: {err}", "danger")
        current_app.logger.error(f"Error DB buscando serie en editar (ID: {serie_id}): {err}")
        return redirect(url_for('main.listar_series'))
    finally:
        if cursor: cursor.close()

    if not serie_actual:
        flash(f"Configuración de serie con ID {serie_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_series'))

    # Cargar sucursales activas y tipos de comprobante para los dropdowns
    sucursales_activas = []
    tipos_comprobante_opciones = ["Nota de Venta", "Boleta Electrónica", "Factura Electrónica", "Otro"]
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar sucursales para el formulario: {err_load}", "danger")
    finally:
        if cursor: cursor.close()
    
    form_titulo = f"Editar Serie: {serie_actual.get('serie', '')}"
    action_url_form = url_for('main.editar_serie', serie_id=serie_id)

    if request.method == 'POST':
        sucursal_id_str = request.form.get('sucursal_id')
        tipo_comprobante = request.form.get('tipo_comprobante')
        serie_nueva = request.form.get('serie', '').strip().upper()
        ultimo_numero_usado_str = request.form.get('ultimo_numero_usado', '0')
        activo_nuevo = 'activo' in request.form

        errores = []
        sucursal_id = None
        if not sucursal_id_str: errores.append("Debe seleccionar una sucursal.")
        else:
            try: sucursal_id = int(sucursal_id_str)
            except ValueError: errores.append("Sucursal seleccionada inválida.")
        
        if not tipo_comprobante: errores.append("Debe seleccionar un tipo de comprobante.")
        if not serie_nueva: errores.append("El código de la serie es obligatorio.")
        
        ultimo_numero_usado = 0
        try:
            ultimo_numero_usado = int(ultimo_numero_usado_str)
            if ultimo_numero_usado < 0:
                errores.append("El último número usado no puede ser negativo.")
        except (ValueError, TypeError):
            errores.append("El último número usado debe ser un número entero.")
        
        # Validar unicidad de la combinación (sucursal, tipo, serie) si ha cambiado
        if (sucursal_id != serie_actual.get('sucursal_id') or 
            tipo_comprobante != serie_actual.get('tipo_comprobante') or 
            serie_nueva.lower() != serie_actual.get('serie', '').lower()):
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM comprobante_series WHERE sucursal_id = %s AND tipo_comprobante = %s AND serie = %s AND id != %s", 
                               (sucursal_id, tipo_comprobante, serie_nueva, serie_id))
                if cursor.fetchone():
                    errores.append(f'Error: La combinación de sucursal, tipo y serie ("{serie_nueva}") ya existe.')
            except mysql.connector.Error as err_check:
                current_app.logger.error(f"Error DB verificando unicidad de serie: {err_check}")
                errores.append("Error al verificar la unicidad de la serie.")
            finally:
                if cursor: cursor.close()

        if errores:
            for error_msg in errores:
                flash(error_msg, 'warning')
            return render_template('configuracion/form_serie.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   serie_item=serie_actual,
                                   sucursales=sucursales_activas,
                                   tipos_comprobante=tipos_comprobante_opciones,
                                   form_data=request.form)
        else:
            # Actualizar la serie en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = """UPDATE comprobante_series SET 
                                    sucursal_id = %s, tipo_comprobante = %s, serie = %s, 
                                    ultimo_numero_usado = %s, activo = %s
                                WHERE id = %s"""
                val_update = (sucursal_id, tipo_comprobante, serie_nueva, 
                              ultimo_numero_usado, activo_nuevo, serie_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'La serie "{serie_nueva}" ha sido actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_series'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                if err_upd.errno == 1062:
                    flash(f'Error de dato duplicado al actualizar: La combinación de sucursal, tipo y serie ya existe.', 'danger')
                else:
                    flash(f"Error al actualizar la serie: {err_upd}", 'danger')
                current_app.logger.error(f"Error DB en POST editar_serie (ID: {serie_id}): {err_upd}")
            finally:
                if cursor: cursor.close()
            
            return render_template('configuracion/form_serie.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   serie_item=serie_actual,
                                   sucursales=sucursales_activas,
                                   tipos_comprobante=tipos_comprobante_opciones,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales de la serie
    return render_template('configuracion/form_serie.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           serie_item=serie_actual,
                           sucursales=sucursales_activas,
                           tipos_comprobante=tipos_comprobante_opciones)
    
@main_bp.route('/configuracion/series/toggle_activo/<int:serie_id>', methods=['GET'])
@login_required
@admin_required
def toggle_activo_serie(serie_id):
    """
    Cambia el estado 'activo' de una configuración de serie.
    """
    serie_actual = None
    db_conn = get_db()
    cursor = None

    try:
        cursor = db_conn.cursor(dictionary=True)
        # Obtener el estado actual de la serie
        cursor.execute("SELECT id, serie, tipo_comprobante, activo FROM comprobante_series WHERE id = %s", (serie_id,))
        serie_actual = cursor.fetchone()

        if not serie_actual:
            flash(f'Configuración de serie con ID {serie_id} no encontrada.', 'warning')
            return redirect(url_for('main.listar_series'))

        nuevo_estado_activo = not serie_actual['activo']
        
        # Actualizar el estado en la base de datos
        # Reutilizamos el cursor ya que la operación de lectura ya terminó
        cursor.execute("UPDATE comprobante_series SET activo = %s WHERE id = %s", (nuevo_estado_activo, serie_id))
        db_conn.commit()
        
        mensaje_estado = "activada" if nuevo_estado_activo else "desactivada"
        flash(f'La serie "{serie_actual["serie"]}" para "{serie_actual["tipo_comprobante"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except mysql.connector.Error as err:
        if db_conn:
            db_conn.rollback()
        flash(f'Error al cambiar el estado de la serie: {err}', 'danger')
        current_app.logger.error(f"Error DB en toggle_activo_serie (ID: {serie_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_series'))    

@main_bp.route('/api/series_por_sucursal_y_tipo', methods=['GET'])
@login_required
@admin_required
def api_get_series_por_sucursal_y_tipo():
    """
    API endpoint para obtener las series activas basadas en una sucursal y tipo de comprobante.
    Devuelve una lista de series en formato JSON.
    """
    sucursal_id_str = request.args.get('sucursal_id')
    tipo_comprobante = request.args.get('tipo_comprobante')

    if not sucursal_id_str or not tipo_comprobante:
        return jsonify({"error": "Faltan parámetros: sucursal_id y tipo_comprobante son requeridos."}), 400

    try:
        sucursal_id = int(sucursal_id_str)
    except ValueError:
        return jsonify({"error": "sucursal_id inválido."}), 400

    series_disponibles = []
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        sql = """
            SELECT serie FROM comprobante_series 
            WHERE sucursal_id = %s AND tipo_comprobante = %s AND activo = TRUE
            ORDER BY serie
        """
        cursor.execute(sql, (sucursal_id, tipo_comprobante))
        resultados = cursor.fetchall()
        # Creamos una lista simple de strings con las series
        series_disponibles = [row['serie'] for row in resultados]
    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_get_series: {err}")
        return jsonify({"error": "Error interno al consultar las series."}), 500
    finally:
        if cursor:
            cursor.close()
    
    return jsonify(series_disponibles)


# --- RUTAS PARA FINANZAS / GASTOS ---

@main_bp.route('/finanzas/categorias_gastos')
@login_required
@admin_required
def listar_categorias_gastos():
    """
    Muestra la lista de todas las categorías de gastos.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_gastos ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las categorías de gastos: {err}", "danger")
        current_app.logger.error(f"Error en listar_categorias_gastos: {err}")
        lista_de_categorias = []
        
    return render_template('finanzas/lista_categorias_gastos.html', 
                           categorias=lista_de_categorias,
                           titulo_pagina="Categorías de Gastos")

@main_bp.route('/finanzas/categorias_gastos/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_categoria_gasto():
    """
    Muestra el formulario para registrar una nueva categoría de gasto (GET)
    y procesa la creación (POST).
    """
    form_titulo = "Registrar Nueva Categoría de Gasto"
    action_url_form = url_for('main.nueva_categoria_gasto')

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')

        if not nombre:
            flash('El nombre de la categoría es obligatorio.', 'warning')
            return render_template('finanzas/form_categoria_gasto.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

        cursor_insert = None
        try:
            db = get_db()
            cursor_insert = db.cursor()
            sql = "INSERT INTO categorias_gastos (nombre, descripcion) VALUES (%s, %s)"
            val = (nombre, (descripcion if descripcion else None))
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Categoría de gasto "{nombre}" registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_categorias_gastos'))
        except mysql.connector.Error as err:
            db.rollback()
            if err.errno == 1062: # Error de entrada duplicada (nombre UNIQUE)
                flash(f'Error: Ya existe una categoría de gasto con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la categoría: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_categoria_gasto (POST): {err}")
            return render_template('finanzas/form_categoria_gasto.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        finally:
            if cursor_insert:
                cursor_insert.close()

    # Método GET: muestra el formulario vacío
    return render_template('finanzas/form_categoria_gasto.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form)
    
@main_bp.route('/finanzas/categorias_gastos/editar/<int:categoria_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_categoria_gasto(categoria_id):
    """
    Muestra el formulario para editar una categoría de gasto existente (GET)
    y procesa la actualización (POST).
    """
    db_conn = get_db()
    cursor = None 

    # Obtener la categoría actual para editar
    categoria_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_gastos WHERE id = %s", (categoria_id,))
        categoria_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar la categoría de gasto: {err}", "danger")
        current_app.logger.error(f"Error DB buscando categoría de gasto en editar (ID: {categoria_id}): {err}")
        return redirect(url_for('main.listar_categorias_gastos'))
    finally:
        if cursor: 
            cursor.close()
            cursor = None 

    if not categoria_actual:
        flash(f"Categoría de gasto con ID {categoria_id} no encontrada.", "warning")
        return redirect(url_for('main.listar_categorias_gastos'))

    form_titulo = f"Editar Categoría: {categoria_actual.get('nombre', '')}"
    action_url_form = url_for('main.editar_categoria_gasto', categoria_id=categoria_id)

    if request.method == 'POST':
        nombre_nuevo = request.form.get('nombre')
        descripcion_nueva = request.form.get('descripcion')
        
        errores = []
        if not nombre_nuevo:
            errores.append('El nombre de la categoría es obligatorio.')

        # Validar unicidad del nombre si ha cambiado
        if nombre_nuevo and nombre_nuevo.lower() != categoria_actual.get('nombre', '').lower():
            try:
                cursor = db_conn.cursor(dictionary=True)
                cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = %s AND id != %s", (nombre_nuevo, categoria_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra categoría de gasto con el nombre "{nombre_nuevo}".')
            except mysql.connector.Error as err_check:
                current_app.logger.error(f"Error DB verificando nombre de categoría de gasto: {err_check}")
                errores.append("Error al verificar la disponibilidad del nombre.")
            finally:
                if cursor: cursor.close(); cursor = None
        
        if errores:
            for error_msg in errores:
                flash(error_msg, 'warning')
            return render_template('finanzas/form_categoria_gasto.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   categoria=categoria_actual, # 'categoria' coincide con la variable en el form
                                   form_data=request.form)
        else:
            # Actualizar la categoría en la BD
            try:
                cursor = db_conn.cursor()
                sql_update = "UPDATE categorias_gastos SET nombre = %s, descripcion = %s WHERE id = %s"
                val_update = (nombre_nuevo, (descripcion_nueva if descripcion_nueva else None), categoria_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'Categoría de gasto "{nombre_nuevo}" actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_categorias_gastos'))
            except mysql.connector.Error as err_upd:
                db_conn.rollback()
                if err_upd.errno == 1062:
                     flash(f'Error: Ya existe una categoría de gasto con el nombre "{nombre_nuevo}".', 'danger')
                else:
                    flash(f"Error al actualizar la categoría de gasto: {err_upd}", 'danger')
                current_app.logger.error(f"Error DB en POST editar_categoria_gasto (ID: {categoria_id}): {err_upd}")
            finally:
                if cursor: cursor.close()
            
            return render_template('finanzas/form_categoria_gasto.html',
                                   es_nueva=False,
                                   titulo_form=form_titulo,
                                   action_url=action_url_form,
                                   categoria=categoria_actual,
                                   form_data=request.form)

    # Método GET: Mostrar el formulario con los datos actuales
    return render_template('finanzas/form_categoria_gasto.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           categoria=categoria_actual)

@main_bp.route('/finanzas/categorias_gastos/eliminar/<int:categoria_id>', methods=['GET'])
@login_required
@admin_required
def eliminar_categoria_gasto(categoria_id):
    """
    Elimina una categoría de gasto existente, verificando primero que no tenga gastos asociados.
    """
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor(dictionary=True)

        # 1. Verificar si la categoría tiene gastos asociados antes de intentar borrar
        cursor.execute("SELECT COUNT(*) as count FROM gastos WHERE categoria_gasto_id = %s", (categoria_id,))
        count_result = cursor.fetchone()
        
        if count_result and count_result['count'] > 0:
            flash(f"No se puede eliminar la categoría porque tiene {count_result['count']} gasto(s) asociado(s).", "warning")
            return redirect(url_for('main.listar_categorias_gastos'))

        # 2. Si no hay gastos asociados, proceder a eliminar la categoría
        cursor.execute("DELETE FROM categorias_gastos WHERE id = %s", (categoria_id,))
        db_conn.commit()

        if cursor.rowcount > 0:
            flash('Categoría de gasto eliminada exitosamente!', 'success')
        else:
            flash('No se encontró la categoría de gasto o no se pudo eliminar.', 'warning')
            
    except mysql.connector.Error as err:
        db_conn.rollback()
        # Este error podría ocurrir si, a pesar de nuestra comprobación, existe una restricción de FK
        # que no consideramos (quizás en otra tabla futura). Es bueno manejarlo.
        if '1451' in str(err): 
            flash('No se puede eliminar esta categoría porque está en uso en otra parte del sistema.', 'danger')
        else:
            flash(f"Error al eliminar la categoría de gasto: {err}", 'danger')
        current_app.logger.error(f"Error DB en eliminar_categoria_gasto (ID: {categoria_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_categorias_gastos'))

@main_bp.route('/finanzas/gastos')
@login_required
@admin_required
def listar_gastos():
    """
    Muestra una lista de todos los gastos registrados.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        # Unimos con otras tablas para obtener nombres en lugar de solo IDs
        sql = """
            SELECT 
                g.id, g.fecha, g.descripcion, g.monto, g.metodo_pago,
                s.nombre AS sucursal_nombre,
                cg.nombre AS categoria_nombre,
                CONCAT(e.nombres, ' ', e.apellidos) AS colaborador_nombre
            FROM gastos g
            JOIN sucursales s ON g.sucursal_id = s.id
            JOIN categorias_gastos cg ON g.categoria_gasto_id = cg.id
            JOIN empleados e ON g.registrado_por_colaborador_id = e.id
            ORDER BY g.fecha DESC, g.id DESC
        """
        cursor.execute(sql)
        lista_de_gastos = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los gastos: {err}", "danger")
        current_app.logger.error(f"Error en listar_gastos: {err}")
        lista_de_gastos = []
        
    return render_template('finanzas/lista_gastos.html', 
                           gastos=lista_de_gastos,
                           titulo_pagina="Historial de Gastos")

@main_bp.route('/finanzas/gastos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_gasto():
    """
    Muestra el formulario para registrar un nuevo gasto (GET)
    y procesa la creación del gasto (POST), incluyendo detalles opcionales del comprobante.
    """
    db_conn = get_db()
    
    # Cargar datos para los menús desplegables (necesario para GET y para re-renderizar en POST con error)
    sucursales_activas = []
    categorias_gastos = []
    colaboradores_activos = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM categorias_gastos ORDER BY nombre")
            categorias_gastos = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar datos para el formulario de gasto: {err_load}", "danger")
        current_app.logger.error(f"Error DB cargando dropdowns en nuevo_gasto: {err_load}")

    form_titulo = "Registrar Nuevo Gasto"
    action_url_form = url_for('main.nuevo_gasto')

    if request.method == 'POST':
        # Recoger todos los campos del formulario
        sucursal_id_str = request.form.get('sucursal_id')
        categoria_gasto_id_str = request.form.get('categoria_gasto_id')
        registrado_por_colaborador_id_str = request.form.get('registrado_por_colaborador_id')
        fecha_str = request.form.get('fecha')
        descripcion = request.form.get('descripcion')
        monto_str = request.form.get('monto')
        metodo_pago = request.form.get('metodo_pago')
        
        # Nuevos campos del comprobante
        comprobante_tipo = request.form.get('comprobante_tipo', '').strip()
        comprobante_serie = request.form.get('comprobante_serie', '').strip()
        comprobante_numero = request.form.get('comprobante_numero', '').strip()
        comprobante_ruc_emisor = request.form.get('comprobante_ruc_emisor', '').strip()
        comprobante_razon_social_emisor = request.form.get('comprobante_razon_social_emisor', '').strip()
        
        errores = []
        if not sucursal_id_str: errores.append("Debe seleccionar una sucursal.")
        if not categoria_gasto_id_str: errores.append("Debe seleccionar una categoría de gasto.")
        if not registrado_por_colaborador_id_str: errores.append("Debe seleccionar el colaborador que registra el gasto.")
        if not fecha_str: errores.append("La fecha es obligatoria.")
        if not descripcion or not descripcion.strip(): errores.append("La descripción es obligatoria.")
        if not monto_str: errores.append("El monto es obligatorio.")
        if not metodo_pago: errores.append("El método de pago es obligatorio.")

        monto = 0.0
        try:
            monto = float(monto_str)
            if monto <= 0: errores.append("El monto debe ser un valor positivo.")
        except (ValueError, TypeError):
            errores.append("El monto debe ser un número válido.")
        
        if errores:
            for error in errores: flash(error, 'warning')
        else:
            cursor_insert = None
            try:
                # Si no hay errores, proceder con la inserción
                cursor_insert = db_conn.cursor()
                sql = """INSERT INTO gastos 
                            (sucursal_id, categoria_gasto_id, fecha, descripcion, monto, metodo_pago, 
                             registrado_por_colaborador_id, comprobante_tipo, comprobante_serie, 
                             comprobante_numero, comprobante_ruc_emisor, comprobante_razon_social_emisor)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                val = (int(sucursal_id_str), int(categoria_gasto_id_str), fecha_str, descripcion, monto, 
                       metodo_pago, int(registrado_por_colaborador_id_str),
                       (comprobante_tipo if comprobante_tipo else None),
                       (comprobante_serie if comprobante_serie else None),
                       (comprobante_numero if comprobante_numero else None),
                       (comprobante_ruc_emisor if comprobante_ruc_emisor else None),
                       (comprobante_razon_social_emisor if comprobante_razon_social_emisor else None)
                      )
                cursor_insert.execute(sql, val)
                db_conn.commit()
                flash("Gasto registrado exitosamente.", "success")
                return redirect(url_for('main.listar_gastos')) # Redirigir a la lista de gastos
            except mysql.connector.Error as err:
                db_conn.rollback()
                flash(f"Error al registrar el gasto: {err}", "danger")
                current_app.logger.error(f"Error en nuevo_gasto (POST): {err}")
            finally:
                if cursor_insert: cursor_insert.close()
        
        # Si hubo un error de validación o de BD, se llega aquí. Re-renderizar el formulario.
        return render_template('finanzas/form_gasto.html', 
                               form_data=request.form, 
                               es_nueva=True, 
                               titulo_form=form_titulo,
                               action_url=action_url_form, 
                               sucursales=sucursales_activas,
                               categorias_gastos=categorias_gastos, 
                               colaboradores=colaboradores_activos)

    # Método GET: muestra el formulario vacío
    return render_template('finanzas/form_gasto.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form, 
                           sucursales=sucursales_activas,
                           categorias_gastos=categorias_gastos, 
                           colaboradores=colaboradores_activos)

@main_bp.route('/finanzas/gastos/editar/<int:gasto_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_gasto(gasto_id):
    db_conn = get_db()
    cursor = None 

    # Obtener el gasto actual para editar
    gasto_actual = None
    try:
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM gastos WHERE id = %s", (gasto_id,))
        gasto_actual = cursor.fetchone()
    except mysql.connector.Error as err:
        flash(f"Error al buscar el gasto: {err}", "danger")
        current_app.logger.error(f"Error DB buscando gasto en editar (ID: {gasto_id}): {err}")
        return redirect(url_for('main.listar_gastos'))
    finally:
        if cursor: cursor.close()

    if not gasto_actual:
        flash(f"Gasto con ID {gasto_id} no encontrado.", "warning")
        return redirect(url_for('main.listar_gastos'))

    # Cargar datos para los menús desplegables
    sucursales_activas, categorias_gastos, colaboradores_activos = [], [], []
    try:
        with db_conn.cursor(dictionary=True) as cursor_dd:
            cursor_dd.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor_dd.fetchall()
        with db_conn.cursor(dictionary=True) as cursor_dd:
            cursor_dd.execute("SELECT id, nombre FROM categorias_gastos ORDER BY nombre")
            categorias_gastos = cursor_dd.fetchall()
        with db_conn.cursor(dictionary=True) as cursor_dd:
            cursor_dd.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor_dd.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar datos para el formulario: {err_load}", "danger")

    form_titulo = f"Editar Gasto #{gasto_actual['id']}"
    action_url_form = url_for('main.editar_gasto', gasto_id=gasto_id)

    if request.method == 'POST':
        # Recoger datos del formulario
        sucursal_id_str = request.form.get('sucursal_id')
        categoria_gasto_id_str = request.form.get('categoria_gasto_id')
        registrado_por_colaborador_id_str = request.form.get('registrado_por_colaborador_id')
        fecha_str = request.form.get('fecha')
        descripcion = request.form.get('descripcion')
        monto_str = request.form.get('monto')
        metodo_pago = request.form.get('metodo_pago')
        comprobante_tipo = request.form.get('comprobante_tipo', '').strip()
        comprobante_serie = request.form.get('comprobante_serie', '').strip()
        comprobante_numero = request.form.get('comprobante_numero', '').strip()
        comprobante_ruc_emisor = request.form.get('comprobante_ruc_emisor', '').strip()
        comprobante_razon_social_emisor = request.form.get('comprobante_razon_social_emisor', '').strip()
        
        # Validaciones (similar a nuevo_gasto)
        errores = []
        # ... (puedes añadir la misma lógica de validación que en nuevo_gasto aquí)
        if not descripcion or not descripcion.strip():
            errores.append("La descripción es obligatoria.")
        
        if errores:
            for error in errores: flash(error, 'warning')
            # Re-renderizar con los datos para que el usuario corrija
            return render_template('finanzas/form_gasto.html', 
                                   es_nueva=False, form_data=request.form, gasto=gasto_actual,
                                   titulo_form=form_titulo, action_url=action_url_form,
                                   sucursales=sucursales_activas, categorias_gastos=categorias_gastos,
                                   colaboradores=colaboradores_activos)
        
        # Si no hay errores, proceder con la actualización
        try:
            with db_conn.cursor() as cursor_update:
                sql_update = """UPDATE gastos SET 
                                    sucursal_id = %s, categoria_gasto_id = %s, fecha = %s, 
                                    descripcion = %s, monto = %s, metodo_pago = %s, 
                                    registrado_por_colaborador_id = %s, comprobante_tipo = %s, 
                                    comprobante_serie = %s, comprobante_numero = %s, 
                                    comprobante_ruc_emisor = %s, comprobante_razon_social_emisor = %s
                                WHERE id = %s"""
                val_update = (
                    int(sucursal_id_str), int(categoria_gasto_id_str), fecha_str, descripcion, 
                    float(monto_str), metodo_pago, int(registrado_por_colaborador_id_str),
                    (comprobante_tipo if comprobante_tipo else None),
                    (comprobante_serie if comprobante_serie else None),
                    (comprobante_numero if comprobante_numero else None),
                    (comprobante_ruc_emisor if comprobante_ruc_emisor else None),
                    (comprobante_razon_social_emisor if comprobante_razon_social_emisor else None),
                    gasto_id
                )
                cursor_update.execute(sql_update, val_update)
            db_conn.commit()
            flash("Gasto actualizado exitosamente.", "success")
            return redirect(url_for('main.listar_gastos'))
        except mysql.connector.Error as err:
            db_conn.rollback()
            flash(f"Error al actualizar el gasto: {err}", "danger")
            current_app.logger.error(f"Error DB en editar_gasto (POST): {err}")
            # Volver a mostrar el formulario con los datos que se intentaron guardar
            return render_template('finanzas/form_gasto.html', 
                                   es_nueva=False, form_data=request.form, gasto=gasto_actual,
                                   titulo_form=form_titulo, action_url=action_url_form,
                                   sucursales=sucursales_activas, categorias_gastos=categorias_gastos,
                                   colaboradores=colaboradores_activos)

    # Método GET: Mostrar el formulario con los datos actuales
    # Formatear la fecha para que el input type="date" la muestre correctamente
    if gasto_actual.get('fecha') and isinstance(gasto_actual['fecha'], date):
        gasto_actual['fecha'] = gasto_actual['fecha'].strftime('%Y-%m-%d')
        
    return render_template('finanzas/form_gasto.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           gasto=gasto_actual, # 'gasto' para que coincida con el form
                           sucursales=sucursales_activas,
                           categorias_gastos=categorias_gastos,
                           colaboradores=colaboradores_activos)

@main_bp.route('/finanzas/gastos/eliminar/<int:gasto_id>', methods=['GET'])
@login_required
@admin_required
def eliminar_gasto(gasto_id):
    """
    Elimina un registro de gasto de forma permanente.
    """
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM gastos WHERE id = %s", (gasto_id,))
        db_conn.commit()

        if cursor.rowcount > 0:
            flash('Registro de gasto eliminado exitosamente.', 'success')
        else:
            flash('No se encontró el gasto o no se pudo eliminar.', 'warning')
            
    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error al eliminar el registro de gasto: {err}", 'danger')
        current_app.logger.error(f"Error DB en eliminar_gasto (ID: {gasto_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_gastos'))

@main_bp.route('/compras/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_compra():
    """
    Maneja la visualización (GET) y el procesamiento (POST) del formulario de nueva compra.
    """
    db_conn = get_db()
    
    # --- Cargar datos para los menús desplegables ---
    proveedores_activos, sucursales_activas, productos_activos = [], [], []
    tipos_comprobante_compra = ["Factura", "Boleta de Venta", "Guía de Remisión", "Otro"]
    estados_pago_compra = ["Pagada", "Pendiente de Pago", "Crédito"]
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre_empresa FROM proveedores WHERE activo = TRUE ORDER BY nombre_empresa")
            proveedores_activos = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            # Consulta actualizada para incluir el nombre de la marca
            sql_productos_compra = """
                SELECT 
                    p.id, p.nombre, p.precio_compra,
                    m.nombre AS marca_nombre
                FROM productos p
                LEFT JOIN marcas m ON p.marca_id = m.id
                WHERE p.activo = TRUE 
                ORDER BY p.nombre, m.nombre
            """
            cursor.execute(sql_productos_compra)
            productos_activos = cursor.fetchall()
    except mysql.connector.Error as err_load:
        flash(f"Error al cargar datos para el formulario de compra: {err_load}", "danger")
        current_app.logger.error(f"Error DB cargando dropdown data en nueva_compra: {err_load}")

    # --- Lógica para el método POST ---
    if request.method == 'POST':
        cursor_post = None
        try:
            # 1. Recoger datos del formulario
            proveedor_id_str = request.form.get('proveedor_id')
            sucursal_id_str = request.form.get('sucursal_id')
            fecha_compra_str = request.form.get('fecha_compra')
            tipo_comprobante = request.form.get('tipo_comprobante', '').strip()
            serie_numero_comprobante = request.form.get('serie_numero_comprobante', '').strip()
            estado_pago = request.form.get('estado_pago')
            notas = request.form.get('notas', '').strip()
            items_json_str = request.form.get('items_compra_json')
            monto_impuestos_str = request.form.get('monto_impuestos', '0.0')

            # 2. Validar datos
            errores = []
            if not proveedor_id_str: errores.append("Debe seleccionar un proveedor.")
            if not sucursal_id_str: errores.append("Debe seleccionar la sucursal.")
            if not fecha_compra_str: errores.append("La fecha de compra es obligatoria.")
            lista_items = json.loads(items_json_str) if items_json_str else []
            if not lista_items:
                errores.append("Debe añadir al menos un producto a la compra.")
            if errores:
                raise ValueError("; ".join(errores))

            # 3. Recalcular totales en el servidor
            subtotal_compra = sum(float(item['cantidad']) * float(item['costo_unitario']) for item in lista_items)
            impuestos = float(monto_impuestos_str if monto_impuestos_str.strip() else 0.0)
            total_compra = subtotal_compra + impuestos

            # 4. Guardar en BD (Transacción Implícita)
            # NO hay db_conn.start_transaction() aquí
            cursor_post = db_conn.cursor()
            
            
            sql_compra = """
                INSERT INTO compras (proveedor_id, sucursal_id, fecha_compra, tipo_comprobante, 
                                     serie_numero_comprobante, monto_subtotal, monto_impuestos, monto_total,
                                     estado_pago, notas)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            val_compra = (int(proveedor_id_str), int(sucursal_id_str), fecha_compra_str, (tipo_comprobante or None), (serie_numero_comprobante or None), subtotal_compra, impuestos, total_compra, estado_pago, (notas or None))
            cursor_post.execute(sql_compra, val_compra)
            compra_id = cursor_post.lastrowid

            for item in lista_items:
                producto_id = int(item['producto_id'])
                cantidad = int(item['cantidad'])
                costo_unitario = float(item['costo_unitario'])
                subtotal_item = cantidad * costo_unitario
                sql_item = "INSERT INTO compra_items (compra_id, producto_id, cantidad, costo_unitario, subtotal) VALUES (%s, %s, %s, %s, %s)"
                val_item = (compra_id, producto_id, cantidad, costo_unitario, subtotal_item)
                cursor_post.execute(sql_item, val_item)
                sql_stock = "UPDATE productos SET stock_actual = stock_actual + %s WHERE id = %s"
                cursor_post.execute(sql_stock, (cantidad, producto_id))
            
            db_conn.commit()
            flash(f"Compra #{compra_id} registrada exitosamente. El stock ha sido actualizado.", "success")
            return redirect(url_for('main.listar_compras'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: 
                db_conn.rollback()
            flash(f"No se pudo guardar la compra. Error: {str(e)}", "warning")
            current_app.logger.error(f"Error procesando compra: {e}")
            
            # Si hubo un error, re-renderizar el formulario
            return render_template('compras/form_compra.html', 
                                   form_data=request.form, 
                                   titulo_form="Registrar Nueva Compra (Corregir Errores)",
                                   action_url=url_for('main.nueva_compra'),
                                   proveedores=proveedores_activos,
                                   sucursales=sucursales_activas,
                                   productos=productos_activos,
                                   tipos_comprobante=tipos_comprobante_compra,
                                   estados_pago=estados_pago_compra)
        finally:
            if cursor_post: cursor_post.close()
    
    # --- Lógica para el método GET ---
    return render_template('compras/form_compra.html', 
                           titulo_form="Registrar Nueva Compra",
                           action_url=url_for('main.nueva_compra'),
                           proveedores=proveedores_activos,
                           sucursales=sucursales_activas,
                           productos=productos_activos,
                           tipos_comprobante=tipos_comprobante_compra,
                           estados_pago=estados_pago_compra)

@main_bp.route('/compras')
@login_required
@admin_required
def listar_compras():
    """
    Muestra una lista de todas las compras registradas.
    """
    db_conn = get_db()
    cursor = None
    lista_de_compras = []

    try:
        cursor = db_conn.cursor(dictionary=True)
        # Unimos con proveedores y sucursales para obtener sus nombres
        sql = """
            SELECT 
                c.id AS compra_id,
                c.fecha_compra,
                c.monto_total,
                c.estado_pago,
                c.tipo_comprobante,
                c.serie_numero_comprobante,
                p.nombre_empresa AS proveedor_nombre,
                s.nombre AS sucursal_nombre
            FROM compras c
            JOIN proveedores p ON c.proveedor_id = p.id
            JOIN sucursales s ON c.sucursal_id = s.id
            ORDER BY c.fecha_compra DESC, c.id DESC
        """
        
        cursor.execute(sql)
        lista_de_compras = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder al historial de compras: {err}", "danger")
        current_app.logger.error(f"Error en listar_compras: {err}")
    finally:
        if cursor:
            cursor.close()
            
    return render_template('compras/lista_compras.html', 
                           compras=lista_de_compras,
                           titulo_pagina="Historial de Compras")

@main_bp.route('/compras/detalle/<int:compra_id>')
@login_required
@admin_required
def ver_detalle_compra(compra_id):
    """
    Muestra los detalles completos de una compra específica, incluyendo sus ítems.
    """
    db_conn = get_db()
    cursor = None
    compra_cabecera = None
    compra_detalle_items = []

    try:
        cursor = db_conn.cursor(dictionary=True)
        
        # 1. Obtener la cabecera de la compra
        sql_cabecera = """
            SELECT 
                c.id AS compra_id, c.fecha_compra, c.fecha_recepcion,
                c.monto_subtotal, c.monto_impuestos, c.monto_total,
                c.estado_pago, c.tipo_comprobante, c.serie_numero_comprobante, c.notas,
                p.nombre_empresa AS proveedor_nombre,
                s.nombre AS sucursal_nombre
            FROM compras c
            JOIN proveedores p ON c.proveedor_id = p.id
            JOIN sucursales s ON c.sucursal_id = s.id
            WHERE c.id = %s
        """
        cursor.execute(sql_cabecera, (compra_id,))
        compra_cabecera = cursor.fetchone()
        
        if not compra_cabecera:
            flash(f"Compra con ID {compra_id} no encontrada.", "warning")
            return redirect(url_for('main.listar_compras'))

        # 2. Obtener los ítems de detalle de la compra
        sql_items = """
            SELECT 
                ci.cantidad, ci.costo_unitario, ci.subtotal,
                p.nombre AS producto_nombre,
                p.codigo_barras,
                m.nombre AS marca_nombre
            FROM compra_items ci
            JOIN productos p ON ci.producto_id = p.id
            LEFT JOIN marcas m ON p.marca_id = m.id
            WHERE ci.compra_id = %s
            ORDER BY p.nombre
        """
        cursor.execute(sql_items, (compra_id,))
        compra_detalle_items = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al acceder a los detalles de la compra: {err}", "danger")
        current_app.logger.error(f"Error en ver_detalle_compra (ID: {compra_id}): {err}")
        return redirect(url_for('main.listar_compras'))
    finally:
        if cursor:
            cursor.close()
            
    return render_template('compras/ver_compra.html', 
                           compra=compra_cabecera, 
                           items=compra_detalle_items,
                           titulo_pagina=f"Detalle de Compra #{compra_cabecera.get('compra_id', compra_id)}")


@main_bp.route('/finanzas/caja', methods=['GET'])
@login_required
@admin_required
def pagina_caja():
    """
    Página principal de gestión de caja. Ahora desglosa los egresos por categoría.
    """
    db_conn = get_db()
    sucursal_id_seleccionada = request.args.get('sucursal_id', type=int)
    
    # Inicializar todas las listas de datos
    sucursales_activas, colaboradores_activos = [], []
    sesion_abierta = None
    resumen_sesion = { "ingresos_por_metodo": [], "egresos_por_categoria": [], "efectivo_calculado": 0.0 }
    comisiones_pendientes = []
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Cargar sucursales y colaboradores para los formularios
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
            
            if sucursal_id_seleccionada:
                cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE AND sucursal_id = %s ORDER BY apellidos, nombres", (sucursal_id_seleccionada,))
                colaboradores_activos = cursor.fetchall()
                
                # Buscar sesión de caja ABIERTA
                cursor.execute("SELECT cs.*, e.nombres as apertura_nombres, e.apellidos as apertura_apellidos FROM caja_sesiones cs JOIN empleados e ON cs.usuario_apertura_id = e.id WHERE cs.sucursal_id = %s AND cs.estado = 'Abierta' ORDER BY cs.fecha_hora_apertura DESC LIMIT 1", (sucursal_id_seleccionada,))
                sesion_abierta = cursor.fetchone()

                # Obtener comisiones pendientes para la sucursal seleccionada
                cursor.execute("""
                    SELECT c.id, c.monto_comision, c.fecha_generacion,
                           CONCAT(e.nombres, ' ', e.apellidos) AS colaborador_nombre,
                           vi.descripcion_item_venta, v.id as venta_id
                    FROM comisiones c
                    JOIN empleados e ON c.colaborador_id = e.id
                    JOIN venta_items vi ON c.venta_item_id = vi.id
                    JOIN ventas v ON vi.venta_id = v.id
                    WHERE c.estado = 'Pendiente' AND v.sucursal_id = %s
                    ORDER BY c.fecha_generacion ASC
                """, (sucursal_id_seleccionada,))
                comisiones_pendientes = cursor.fetchall()

                if sesion_abierta:
                    fecha_apertura = sesion_abierta['fecha_hora_apertura']
                    
                    # 1. Calcular ingresos por método de pago
                    sql_ingresos = """
                        SELECT vp.metodo_pago, SUM(vp.monto) as total
                        FROM venta_pagos vp
                        JOIN ventas v ON vp.venta_id = v.id
                        WHERE v.sucursal_id = %s AND v.fecha_venta >= %s AND v.estado_pago != 'Anulado'
                        GROUP BY vp.metodo_pago
                    """
                    cursor.execute(sql_ingresos, (sucursal_id_seleccionada, fecha_apertura))
                    ingresos_por_metodo = cursor.fetchall()
                    
                    # 2. Calcular gastos pagados con 'Efectivo de Caja'
                    sql_gastos = "SELECT SUM(monto) as total FROM gastos WHERE sucursal_id = %s AND fecha >= %s AND metodo_pago = 'Efectivo de Caja'"
                    cursor.execute(sql_gastos, (sucursal_id_seleccionada, fecha_apertura.date()))
                    resultado_gastos = cursor.fetchone()
                    # CORRECCIÓN: Convertir a float, con valor por defecto 0.0
                    total_gastos_efectivo = float(resultado_gastos['total']) if resultado_gastos and resultado_gastos['total'] else 0.0

                    
                    # 2. CORRECCIÓN: Calcular egresos en efectivo DESGLOSADOS POR CATEGORÍA
                    sql_gastos = """
                        SELECT cg.nombre AS categoria_nombre, SUM(g.monto) as total
                        FROM gastos g
                        JOIN categorias_gastos cg ON g.categoria_gasto_id = cg.id
                        WHERE g.sucursal_id = %s AND g.fecha >= %s AND g.metodo_pago = 'Efectivo de Caja'
                        GROUP BY cg.nombre
                        ORDER BY cg.nombre
                    """
                    cursor.execute(sql_gastos, (sucursal_id_seleccionada, fecha_apertura.date()))
                    egresos_por_categoria = cursor.fetchall()
                    
                    # 3. Calcular el efectivo esperado en caja
                    monto_inicial = float(sesion_abierta['monto_inicial_efectivo'])
                    
                    ingresos_efectivo = 0.0
                    for ingreso in ingresos_por_metodo:
                        if ingreso['metodo_pago'].lower() == 'efectivo':
                            ingresos_efectivo = float(ingreso['total'])
                            break
                            
                    total_egresos_efectivo = sum(float(egreso['total']) for egreso in egresos_por_categoria)
                    
                    efectivo_calculado = (monto_inicial + ingresos_efectivo) - total_egresos_efectivo
                    
                    resumen_sesion = {
                        "ingresos_por_metodo": ingresos_por_metodo,
                        "egresos_por_categoria": egresos_por_categoria, # <-- NUEVA LISTA DESGLOSADA
                        "efectivo_calculado": efectivo_calculado
                    }
                    
    except mysql.connector.Error as err:
        flash(f"Error al verificar el estado de la caja: {err}", "danger")

    return render_template('finanzas/pagina_caja.html',
                           sucursales=sucursales_activas,
                           colaboradores=colaboradores_activos,
                           sucursal_seleccionada_id=sucursal_id_seleccionada,
                           sesion_abierta=sesion_abierta,
                           resumen=resumen_sesion,
                           comisiones_pendientes=comisiones_pendientes)    

@main_bp.route('/finanzas/caja/abrir', methods=['POST'])
@login_required
@admin_required
def abrir_caja():
    """
    Procesa la apertura de una nueva sesión de caja, obteniendo el colaborador desde el formulario.
    """
    db_conn = get_db()
    sucursal_id = request.form.get('sucursal_id', type=int)
    monto_inicial = request.form.get('monto_inicial_efectivo', type=float)
    # Obtenemos el ID del colaborador desde el nuevo desplegable del formulario
    usuario_apertura_id = request.form.get('usuario_apertura_id', type=int)

    # Validación de que todos los datos necesarios fueron enviados
    if not sucursal_id or not usuario_apertura_id or monto_inicial is None or monto_inicial < 0:
        flash("Datos inválidos. Se requiere sucursal, colaborador y un monto inicial no negativo.", "warning")
        return redirect(url_for('main.pagina_caja'))

    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Verificar que no haya otra caja abierta para esta sucursal
            cursor.execute("SELECT id FROM caja_sesiones WHERE sucursal_id = %s AND estado = 'Abierta'", (sucursal_id,))
            if cursor.fetchone():
                flash(f"Ya existe una sesión de caja abierta para esta sucursal.", "warning")
                return redirect(url_for('main.pagina_caja'))
            
            # Insertar la nueva sesión de caja
            sql = """
                INSERT INTO caja_sesiones 
                    (sucursal_id, usuario_apertura_id, fecha_hora_apertura, monto_inicial_efectivo, estado)
                VALUES (%s, %s, %s, %s, %s)
            """
            val = (sucursal_id, usuario_apertura_id, datetime.now(), monto_inicial, 'Abierta')
            cursor.execute(sql, val)
            db_conn.commit()
            flash("Caja abierta exitosamente.", "success")

    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error al abrir la caja: {err}", "danger")
        current_app.logger.error(f"Error en abrir_caja: {err}")

    return redirect(url_for('main.pagina_caja'))

@main_bp.route('/finanzas/caja/cerrar/<int:sesion_id>', methods=['POST'])
@login_required
@admin_required
def cerrar_caja(sesion_id):
    """
    Procesa el cierre de una sesión de caja.
    """
    db_conn = get_db()
    
    # 1. Recoger datos del formulario
    monto_contado_str = request.form.get('monto_final_efectivo_contado')
    notas_cierre = request.form.get('notas_cierre', '').strip()
    usuario_cierre_id = request.form.get('usuario_cierre_id', type=int)

    # 2. Validar datos de entrada
    if monto_contado_str is None or not usuario_cierre_id:
        flash("Debe ingresar el monto contado y seleccionar el colaborador que cierra la caja.", "warning")
        return redirect(url_for('main.pagina_caja'))
    
    try:
        monto_contado = float(monto_contado_str)
        if monto_contado < 0:
             flash("El monto contado no puede ser negativo.", "warning")
             return redirect(url_for('main.pagina_caja'))
    except (ValueError, TypeError):
        flash("El monto contado debe ser un número válido.", "warning")
        return redirect(url_for('main.pagina_caja'))

    cursor = None
    try:
        # 3. Iniciar transacción y realizar operaciones
        db_conn.start_transaction()
        cursor = db_conn.cursor(dictionary=True)

        # 3a. Obtener la sesión y asegurarse de que esté abierta, bloqueando la fila
        cursor.execute("SELECT * FROM caja_sesiones WHERE id = %s AND estado = 'Abierta' FOR UPDATE", (sesion_id,))
        sesion_abierta = cursor.fetchone()

        if not sesion_abierta:
            db_conn.rollback() # No hay nada que hacer, pero es buena práctica
            flash("La sesión de caja que intentas cerrar no existe o ya ha sido cerrada.", "warning")
            return redirect(url_for('main.pagina_caja'))

        # 3b. Recalcular los montos en el servidor para máxima seguridad
        fecha_apertura = sesion_abierta['fecha_hora_apertura']
        sucursal_id = sesion_abierta['sucursal_id']
        monto_inicial = float(sesion_abierta['monto_inicial_efectivo'])
        
        # Ingresos en efectivo
        cursor.execute("""
            SELECT SUM(monto) as total 
            FROM venta_pagos vp 
            JOIN ventas v ON vp.venta_id = v.id 
            WHERE v.sucursal_id = %s AND v.fecha_venta >= %s AND vp.metodo_pago = 'Efectivo' AND v.estado_pago != 'Anulado'
        """, (sucursal_id, fecha_apertura))
        ingresos_efectivo = float(cursor.fetchone()['total'] or 0.0)

        # Gastos en efectivo
        cursor.execute("SELECT SUM(monto) as total FROM gastos WHERE sucursal_id = %s AND fecha >= %s AND metodo_pago = 'Efectivo de Caja'", (sucursal_id, fecha_apertura.date()))
        gastos_efectivo = float(cursor.fetchone()['total'] or 0.0)
        
        # TODO: Sumar egresos por pago de comisiones en efectivo aquí cuando se implemente
        comisiones_efectivo = 0.0
        
        # Calcular el saldo final esperado por el sistema
        monto_calculado = (monto_inicial + ingresos_efectivo) - gastos_efectivo - comisiones_efectivo
        diferencia = monto_contado - monto_calculado

        # 3c. Actualizar el registro de la sesión de caja con los datos de cierre
        sql_update = """UPDATE caja_sesiones SET 
                            estado = 'Cerrada', 
                            fecha_hora_cierre = %s,
                            usuario_cierre_id = %s,
                            monto_final_efectivo_contado = %s,
                            monto_final_efectivo_calculado = %s,
                            diferencia_efectivo = %s,
                            notas_cierre = %s
                        WHERE id = %s"""
        val_update = (datetime.now(), usuario_cierre_id, monto_contado, 
                      monto_calculado, diferencia, (notas_cierre or None), sesion_id)
        cursor.execute(sql_update, val_update)
        
        # 4. Confirmar la transacción
        db_conn.commit()
        flash(f"Caja cerrada exitosamente. Diferencia encontrada: S/ {diferencia:.2f}", "success" if abs(diferencia) < 0.1 else "warning")

    except mysql.connector.Error as err:
        if db_conn and db_conn.in_transaction: 
            db_conn.rollback()
        flash(f"Error de base de datos al cerrar la caja: {err}", "danger")
        current_app.logger.error(f"Error DB en cerrar_caja (ID: {sesion_id}): {err}")
    except Exception as e:
        if db_conn and db_conn.in_transaction: 
            db_conn.rollback()
        flash(f"Ocurrió un error inesperado al cerrar la caja: {e}", "danger")
        current_app.logger.error(f"Error inesperado en cerrar_caja (ID: {sesion_id}): {e}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.pagina_caja'))

@main_bp.route('/finanzas/caja/pagar_comisiones', methods=['POST'])
@login_required
@admin_required
def pagar_comisiones_caja():
    """
    Procesa el pago de comisiones seleccionadas desde la página de caja.
    """
    db_conn = get_db()
    cursor = None
    
    # Obtener el sucursal_id de la URL para la redirección
    sucursal_id_para_redirect = request.args.get('sucursal_id')
    
    # Obtener los datos del formulario
    comisiones_a_pagar_ids = request.form.getlist('comision_id')
    caja_sesion_id = request.form.get('caja_sesion_id', type=int)
    # Obtener el ID del colaborador desde el nuevo desplegable del formulario
    registrado_por_id = request.form.get('registrado_por_colaborador_id', type=int)

    # Validaciones
    if not comisiones_a_pagar_ids:
        flash("No se seleccionó ninguna comisión para pagar.", "warning")
        return redirect(url_for('main.pagina_caja', sucursal_id=sucursal_id_para_redirect))
    if not caja_sesion_id or not registrado_por_id:
        flash("No se pudo identificar la sesión de caja o el colaborador que registra el pago. Por favor, seleccione ambos.", "danger")
        return redirect(url_for('main.pagina_caja', sucursal_id=sucursal_id_para_redirect))

    try:
        db_conn.start_transaction()
        cursor = db_conn.cursor(dictionary=True)

        # 1. Validar las comisiones y calcular el total a pagar
        total_pagado = 0.0
        ids_para_update = []
        
        placeholders = ', '.join(['%s'] * len(comisiones_a_pagar_ids))
        sql_select_comisiones = f"SELECT id, monto_comision FROM comisiones WHERE id IN ({placeholders}) AND estado = 'Pendiente' FOR UPDATE"
        cursor.execute(sql_select_comisiones, tuple(comisiones_a_pagar_ids))
        comisiones_a_procesar = cursor.fetchall()
        
        if len(comisiones_a_procesar) != len(comisiones_a_pagar_ids):
            raise ValueError("Algunas de las comisiones seleccionadas ya no están pendientes o no existen.")

        for comision in comisiones_a_procesar:
            total_pagado += float(comision['monto_comision'])
            ids_para_update.append(comision['id'])

        if total_pagado > 0:
            # 2. Registrar un único Gasto por el total de comisiones pagadas
            # Buscar el ID de la categoría "Pago de Comisiones"
            cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Pago de Comisiones'")
            cat_gasto = cursor.fetchone()
            if not cat_gasto:
                cursor.execute("INSERT INTO categorias_gastos (nombre, descripcion) VALUES ('Pago de Comisiones', 'Pagos de comisiones generadas por ventas a colaboradores')")
                categoria_gasto_id = cursor.lastrowid
            else:
                categoria_gasto_id = cat_gasto['id']

            # Obtener sucursal_id de la sesión de caja
            cursor.execute("SELECT sucursal_id FROM caja_sesiones WHERE id = %s", (caja_sesion_id,))
            sesion_info = cursor.fetchone()
            if not sesion_info: raise ValueError("La sesión de caja activa no es válida.")
            sucursal_id_gasto = sesion_info['sucursal_id']
            
            descripcion_gasto = f"Pago de {len(ids_para_update)} comision(es). IDs: {', '.join(map(str, ids_para_update))}."
            
            sql_gasto = """
                INSERT INTO gastos (sucursal_id, categoria_gasto_id, caja_sesion_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            # Usar el 'registrado_por_id' del formulario
            val_gasto = (sucursal_id_gasto, categoria_gasto_id, caja_sesion_id, date.today(), descripcion_gasto, total_pagado, 'Efectivo de Caja', registrado_por_id)
            cursor.execute(sql_gasto, val_gasto)

            # 3. Actualizar el estado de las comisiones a 'Pagada'
            update_placeholders = ', '.join(['%s'] * len(ids_para_update))
            sql_update_comisiones = f"UPDATE comisiones SET estado = 'Pagada', fecha_pago = %s, pago_caja_sesion_id = %s WHERE id IN ({update_placeholders})"
            params_update = [datetime.now(), caja_sesion_id] + ids_para_update
            cursor.execute(sql_update_comisiones, tuple(params_update))
        
        # 4. Confirmar la transacción
        db_conn.commit()
        if total_pagado > 0:
            flash(f"Se registraron exitosamente {len(ids_para_update)} pagos de comisiones por un total de S/ {total_pagado:.2f}.", "success")
        else:
            flash("No se procesaron pagos de comisiones.", "info")

    except (ValueError, mysql.connector.Error, Exception) as e:
        if db_conn and db_conn.in_transaction: 
            db_conn.rollback()
        flash(f"No se pudo registrar el pago de comisiones. Error: {str(e)}", "danger")
        current_app.logger.error(f"Error en pagar_comisiones_caja: {e}")
    finally:
        if cursor:
            cursor.close()

    # Al redirigir, pasamos el sucursal_id para que la página de caja se recargue correctamente
    return redirect(url_for('main.pagina_caja', sucursal_id=sucursal_id_para_redirect))

@main_bp.route('/api/clientes/<int:cliente_id>/puntos', methods=['GET'])
@login_required
def api_get_puntos_cliente(cliente_id):
    """
    API para obtener el saldo de puntos de un cliente específico.
    Versión corregida que garantiza la clave de respuesta correcta.
    """
    if cliente_id == 0:
        return jsonify({"puntos_disponibles": 0})

    db_conn = get_db()
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT puntos_fidelidad FROM clientes WHERE id = %s", (cliente_id,))
            cliente = cursor.fetchone()
            
            if cliente:
                # Obtener el valor, si es nulo (None), convertirlo a 0
                puntos = cliente.get('puntos_fidelidad') or 0
                # Devolver siempre el JSON con la clave que el JavaScript espera
                return jsonify({"puntos_disponibles": puntos})
            else:
                return jsonify({"error": "Cliente no encontrado."}), 404

    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_get_puntos_cliente (ID: {cliente_id}): {err}")
        return jsonify({"error": "Error interno al consultar los puntos del cliente."}), 500


# --- RUTAS PARA REPORTES ---

@main_bp.route('/reportes/estado_resultados', methods=['GET'])
@login_required
@admin_required
def reporte_estado_resultados():
    """
    Muestra el formulario de filtros y, si se proporcionan, genera y muestra
    el reporte de estado de resultados para un período y sucursal.
    """
    db_conn = get_db()
    
    # Obtener los parámetros de la URL (si los hay)
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    sucursal_id_str = request.args.get('sucursal_id')
    
    # Cargar sucursales para el menú desplegable de filtros
    sucursales_activas = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar sucursales: {err}", "danger")

    resultados = None # Inicializamos los resultados como nulos

    # Si se enviaron los filtros, procesar los datos
    if fecha_inicio_str and fecha_fin_str and sucursal_id_str:
        try:
            sucursal_id = int(sucursal_id_str)
            
            # Asegurarse de que el rango de fechas cubra el día completo
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            
            with db_conn.cursor(dictionary=True) as cursor:
                # 1. Calcular Ingresos (de ventas no anuladas)
                sql_ingresos = """
                    SELECT 
                        SUM(subtotal_servicios) as total_servicios, 
                        SUM(subtotal_productos) as total_productos
                    FROM ventas 
                    WHERE sucursal_id = %s AND DATE(fecha_venta) BETWEEN %s AND %s AND estado_pago != 'Anulado'
                """
                cursor.execute(sql_ingresos, (sucursal_id, fecha_inicio, fecha_fin))
                ingresos = cursor.fetchone()
                
                # 2. Calcular Gastos por categoría
                sql_gastos = """
                    SELECT 
                        cg.nombre as categoria, 
                        SUM(g.monto) as total_por_categoria
                    FROM gastos g
                    JOIN categorias_gastos cg ON g.categoria_gasto_id = cg.id
                    WHERE g.sucursal_id = %s AND g.fecha BETWEEN %s AND %s
                    GROUP BY cg.nombre
                    ORDER BY total_por_categoria DESC
                """
                cursor.execute(sql_gastos, (sucursal_id, fecha_inicio, fecha_fin))
                gastos_por_categoria = cursor.fetchall()
                
                # 3. Consolidar los resultados para la plantilla
                total_ingresos_servicios = float(ingresos.get('total_servicios') or 0.0)
                total_ingresos_productos = float(ingresos.get('total_productos') or 0.0)
                total_ingresos = total_ingresos_servicios + total_ingresos_productos
                
                total_gastos = sum(float(g['total_por_categoria']) for g in gastos_por_categoria)
                
                utilidad_neta = total_ingresos - total_gastos

                resultados = {
                    "total_ingresos": total_ingresos,
                    "total_ingresos_servicios": total_ingresos_servicios,
                    "total_ingresos_productos": total_ingresos_productos,
                    "gastos_desglosados": gastos_por_categoria,
                    "total_gastos": total_gastos,
                    "utilidad_neta": utilidad_neta
                }

        except (ValueError, mysql.connector.Error) as e:
            flash(f"Error al generar el reporte: {e}", "danger")
            current_app.logger.error(f"Error generando reporte estado de resultados: {e}")

    return render_template('reportes/estado_resultados.html',
                           titulo_pagina="Reporte de Estado de Resultados",
                           sucursales=sucursales_activas,
                           filtros=request.args, # Pasar los filtros para mantenerlos en el form
                           resultados=resultados)

@main_bp.route('/reportes/liquidacion', methods=['GET'])
@login_required
@admin_required
def reporte_liquidacion():
    """
    Muestra el formulario de filtros y genera la liquidación de pago mensual,
    incluyendo el cálculo automático de bonos basado en reglas.
    """
    db_conn = get_db()
    
    # Obtener los filtros de la URL
    colaborador_id = request.args.get('colaborador_id', type=int)
    hoy = datetime.now()
    anio = request.args.get('anio', default=hoy.year, type=int)
    mes = request.args.get('mes', default=hoy.month, type=int)

    # Cargar colaboradores para el menú desplegable de filtros
    colaboradores_activos = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar la lista de colaboradores: {err}", "danger")

    resultados = None
    # Si se enviaron todos los filtros, generar el reporte
    if colaborador_id and anio and mes:
        try:
            # Primero, verificar si la liquidación para este período ya fue pagada
            with db_conn.cursor(dictionary=True) as cursor:
                 cursor.execute("SELECT * FROM liquidaciones WHERE colaborador_id = %s AND anio = %s AND mes = %s", (colaborador_id, anio, mes))
                 liquidacion_existente = cursor.fetchone()
            
            if liquidacion_existente:
                # Si ya existe, mostramos el historial en lugar de calcular de nuevo
                resultados = {"ya_pagado": True, "liquidacion": liquidacion_existente}
            else:
                # Si no ha sido pagada, calculamos todo desde cero
                _, num_dias_mes = calendar.monthrange(anio, mes)
                fecha_inicio_periodo = date(anio, mes, 1)
                fecha_fin_periodo = date(anio, mes, num_dias_mes)

                with db_conn.cursor(dictionary=True) as cursor:
                    # 1. Obtener datos base del colaborador
                    cursor.execute("SELECT * FROM empleados WHERE id = %s", (colaborador_id,))
                    colaborador_seleccionado = cursor.fetchone()
                    if not colaborador_seleccionado: raise ValueError("Colaborador no encontrado.")
                    sueldo_base = float(colaborador_seleccionado.get('sueldo_base', 0.0))

                    cursor.execute("SELECT monto_cuota FROM cuotas_mensuales WHERE colaborador_id = %s AND anio = %s AND mes = %s", (colaborador_id, anio, mes))
                    cuota_obj = cursor.fetchone()
                    monto_cuota = float(cuota_obj['monto_cuota']) if cuota_obj else 0.0

                    # 2. Calcular Métricas de Rendimiento del Mes
                    cursor.execute("SELECT SUM(vi.valor_produccion) as total FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id WHERE v.empleado_id = %s AND v.estado_pago != 'Anulado' AND DATE(v.fecha_venta) BETWEEN %s AND %s AND vi.servicio_id IS NOT NULL AND vi.es_trabajo_extra = FALSE", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
                    produccion_servicios = float(cursor.fetchone()['total'] or 0.0)
                    
                    cursor.execute("SELECT SUM(c.monto_comision) as total FROM comisiones c JOIN venta_items vi ON c.venta_item_id = vi.id JOIN ventas v ON vi.venta_id = v.id WHERE c.colaborador_id = %s AND vi.producto_id IS NOT NULL AND DATE(c.fecha_generacion) BETWEEN %s AND %s", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
                    suma_comision_productos = float(cursor.fetchone()['total'] or 0.0)

                    cursor.execute("SELECT vi.servicio_id, COUNT(vi.id) as cantidad FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id WHERE v.empleado_id = %s AND v.estado_pago != 'Anulado' AND DATE(v.fecha_venta) BETWEEN %s AND %s AND vi.servicio_id IS NOT NULL GROUP BY vi.servicio_id", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
                    cantidad_por_servicio = {row['servicio_id']: row['cantidad'] for row in cursor.fetchall()}

                    # 3. Evaluar Bonos por Reglas
                    bonos_ganados = []
                    cursor.execute("SELECT * FROM bonos WHERE activo = TRUE")
                    bonos_activos = cursor.fetchall()

                    for bono in bonos_activos:
                        cursor.execute("SELECT * FROM bono_reglas WHERE bono_id = %s", (bono['id'],))
                        reglas_del_bono = cursor.fetchall()
                        
                        todas_las_reglas_cumplidas = True if reglas_del_bono else False
                        for regla in reglas_del_bono:
                            rendimiento_actual = 0
                            if regla['tipo_regla'] == 'PRODUCCION_SERVICIOS': rendimiento_actual = produccion_servicios
                            elif regla['tipo_regla'] == 'SUMA_COMISION_PRODUCTOS': rendimiento_actual = suma_comision_productos
                            elif regla['tipo_regla'] == 'CANTIDAD_SERVICIO': rendimiento_actual = cantidad_por_servicio.get(regla['servicio_id_asociado'], 0)
                            
                            if not eval(f"{rendimiento_actual} {regla['operador']} {regla['valor_objetivo']}"):
                                todas_las_reglas_cumplidas = False
                                break
                        
                        if todas_las_reglas_cumplidas:
                            bonos_ganados.append(bono)

                    # 4. Obtener Comisiones y Ajustes pendientes
                    cursor.execute("SELECT *, DATE_FORMAT(fecha_generacion, '%%d/%m/%Y') as fecha_corta FROM comisiones WHERE colaborador_id = %s AND estado = 'Pendiente' AND DATE(fecha_generacion) BETWEEN %s AND %s", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
                    comisiones_pendientes = cursor.fetchall()
                    total_comisiones = sum(float(c['monto_comision']) for c in comisiones_pendientes)

                    cursor.execute("SELECT * FROM ajustes_pago WHERE colaborador_id = %s AND estado = 'Pendiente' AND fecha BETWEEN %s AND %s", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
                    ajustes_pago = cursor.fetchall()
                    total_otros_bonos = sum(float(a['monto']) for a in ajustes_pago if a['monto'] > 0)
                    total_descuentos = abs(sum(float(a['monto']) for a in ajustes_pago if a['monto'] < 0))

                    # 5. Calcular Totales Finales
                    bono_produccion = max(0, (produccion_servicios - monto_cuota) * 0.50)
                    excedente_produccion = max(0, produccion_servicios - monto_cuota)
                    total_bonos_reglas = sum(float(b['monto_bono']) for b in bonos_ganados)
                    
                    total_ingresos = sueldo_base + bono_produccion + total_comisiones + total_otros_bonos + total_bonos_reglas
                    liquido_a_pagar = total_ingresos - total_descuentos

                    resultados = {
                        "ya_pagado": False,
                        "colaborador": colaborador_seleccionado,
                        "periodo": fecha_inicio_periodo.strftime('%B de %Y').capitalize(),
                        "sueldo_base": sueldo_base, "total_produccion": produccion_servicios,
                        "monto_cuota": monto_cuota, "excedente_produccion": excedente_produccion,
                        "bono_produccion": bono_produccion, "comisiones_pendientes": comisiones_pendientes,
                        "total_comisiones": total_comisiones, "ajustes_pago": ajustes_pago,
                        "total_otros_bonos": total_otros_bonos, "total_descuentos": total_descuentos,
                        "total_ingresos": total_ingresos, "liquido_a_pagar": liquido_a_pagar,
                        "bonos_ganados": bonos_ganados, "total_bonos_reglas": total_bonos_reglas
                    }
        except Exception as e:
            flash(f"Error al generar la liquidación: {e}", "danger")
            current_app.logger.error(f"Error generando liquidación: {e}")

    return render_template('reportes/reporte_liquidacion.html',
                           titulo_pagina="Liquidación de Pago a Colaboradores",
                           colaboradores=colaboradores_activos,
                           filtros=request.args,
                           anio_actual=anio,
                           mes_actual=mes,
                           resultados=resultados)

# --- RUTAS PARA CAMPAÑAS Y PROMOCIONES ---

@main_bp.route('/campanas')
@login_required
@admin_required
def listar_campanas():
    """
    Muestra la lista de todas las campañas de marketing y promociones.
    """
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT *, DATE_FORMAT(fecha_inicio, '%d/%m/%Y') as f_inicio, DATE_FORMAT(fecha_fin, '%d/%m/%Y') as f_fin FROM campanas ORDER BY fecha_inicio DESC")
        lista_de_campanas = cursor.fetchall()
        cursor.close()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a las campañas: {err}", "danger")
        current_app.logger.error(f"Error en listar_campanas: {err}")
        lista_de_campanas = []
        
    return render_template('campanas/lista_campanas.html', 
                           campanas=lista_de_campanas,
                           titulo_pagina="Campañas y Promociones")

@main_bp.route('/campanas/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_campana():
    """
    Muestra el formulario para registrar una nueva campaña (GET)
    y procesa su creación (POST).
    """
    form_titulo = "Registrar Nueva Campaña"
    action_url_form = url_for('main.nueva_campana')
    
    # Definimos los tipos de reglas que nuestro sistema soportará
    tipos_regla_opciones = {
        'DUPLICAR_PUNTOS': 'Duplicar/Multiplicar Puntos',
        'DESCUENTO_PORCENTAJE': 'Descuento en Porcentaje (%)',
        'DESCUENTO_MONTO': 'Descuento en Monto Fijo (S/)'
    }

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        tipo_regla = request.form.get('tipo_regla')
        valor_regla_str = request.form.get('valor_regla')
        activo = 'activo' in request.form

        errores = []
        if not all([nombre, fecha_inicio_str, fecha_fin_str, tipo_regla, valor_regla_str]):
            errores.append("Todos los campos marcados con * son obligatorios.")
        
        # Más validaciones específicas
        try:
            valor_regla = float(valor_regla_str)
        except (ValueError, TypeError):
            errores.append("El valor de la regla debe ser un número.")
            valor_regla = 0 # Asignar para que la plantilla no falle

        if not errores:
            cursor_insert = None
            try:
                db = get_db()
                cursor_insert = db.cursor()
                sql = """INSERT INTO campanas (nombre, descripcion, fecha_inicio, fecha_fin, tipo_regla, valor_regla, activo) 
                         VALUES (%s, %s, %s, %s, %s, %s, %s)"""
                val = (nombre, (descripcion or None), fecha_inicio_str, fecha_fin_str, tipo_regla, valor_regla, activo)
                cursor_insert.execute(sql, val)
                db.commit()
                flash(f'Campaña "{nombre}" registrada exitosamente!', 'success')
                return redirect(url_for('main.listar_campanas'))
            except mysql.connector.Error as err:
                db.rollback()
                if err.errno == 1062:
                    flash(f'Error: Ya existe una campaña con el nombre "{nombre}".', 'danger')
                else:
                    flash(f'Error al registrar la campaña: {err}', 'danger')
            finally:
                if cursor_insert: cursor_insert.close()
        
        # Si hubo errores, mostrar los flashes y re-renderizar el formulario
        for error in errores:
            flash(error, 'warning')
        return render_template('campanas/form_campana.html', 
                               form_data=request.form, es_nueva=True, 
                               titulo_form=form_titulo, action_url=action_url_form,
                               tipos_regla=tipos_regla_opciones)

    # Método GET: muestra el formulario vacío
    return render_template('campanas/form_campana.html', 
                           es_nueva=True, titulo_form=form_titulo,
                           action_url=action_url_form, tipos_regla=tipos_regla_opciones)

# --- Fin de Rutas para Campañas ---

@main_bp.route('/reportes/produccion', methods=['GET'])
@login_required
@admin_required
def reporte_produccion():
    """
    Muestra el reporte de producción por colaborador.
    Versión final que usa 'valor_produccion' para los cálculos.
    """
    db_conn = get_db()
    
    # Obtener los filtros de la URL
    colaborador_id = request.args.get('colaborador_id', type=int)
    sucursal_id = request.args.get('sucursal_id', type=int)
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')

    # Cargar datos para los desplegables de los filtros
    sucursales = []
    colaboradores = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar datos para los filtros: {err}", "danger")

    resultados = None
    if colaborador_id and sucursal_id and fecha_inicio and fecha_fin:
        try:
            with db_conn.cursor(dictionary=True) as cursor:
                # Consulta para el detalle de SERVICIOS
                sql_servicios = """
                    SELECT 
                        v.fecha_venta, 
                        COALESCE(CONCAT(cl.razon_social_nombres, ' ', cl.apellidos), 'Cliente Varios') AS cliente_nombre,
                        s.nombre as servicio_nombre, 
                        vi.precio_unitario_venta, 
                        vi.valor_produccion,
                        vi.usado_como_beneficio,
                        ca.nombre as campana_nombre, 
                        vi.es_trabajo_extra
                    FROM venta_items vi
                    JOIN ventas v ON vi.venta_id = v.id
                    JOIN servicios s ON vi.servicio_id = s.id
                    LEFT JOIN clientes cl ON v.cliente_receptor_id = cl.id
                    LEFT JOIN campanas ca ON v.campana_id = ca.id
                    WHERE v.empleado_id = %s AND v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s
                      AND vi.servicio_id IS NOT NULL
                    ORDER BY v.fecha_venta DESC
                """
                cursor.execute(sql_servicios, (colaborador_id, sucursal_id, fecha_inicio, fecha_fin))
                servicios_vendidos = cursor.fetchall()

                # Consulta para el detalle de PRODUCTOS
                sql_productos = """
                    SELECT 
                        v.fecha_venta, 
                        COALESCE(CONCAT(cl.razon_social_nombres, ' ', cl.apellidos), 'Cliente Varios') AS cliente_nombre,
                        p.nombre as producto_nombre, 
                        m.nombre as marca_nombre, 
                        vi.cantidad, 
                        vi.precio_unitario_venta, 
                        vi.subtotal_item_neto,
                        vi.valor_produccion,
                        com.monto_comision
                    FROM venta_items vi
                    JOIN ventas v ON vi.venta_id = v.id
                    JOIN productos p ON vi.producto_id = p.id
                    LEFT JOIN clientes cl ON v.cliente_receptor_id = cl.id
                    LEFT JOIN marcas m ON p.marca_id = m.id
                    LEFT JOIN comisiones com ON com.venta_item_id = vi.id
                    WHERE v.empleado_id = %s AND v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s
                      AND vi.producto_id IS NOT NULL
                    ORDER BY v.fecha_venta DESC
                """
                cursor.execute(sql_productos, (colaborador_id, sucursal_id, fecha_inicio, fecha_fin))
                productos_vendidos = cursor.fetchall()
                
                # Cálculos para el resumen usando 'valor_produccion'
                total_produccion_servicios = sum(float(s['valor_produccion']) for s in servicios_vendidos)
                total_produccion_productos = sum(float(p['valor_produccion']) for p in productos_vendidos)
                total_comisiones = sum(float(p['monto_comision']) for p in productos_vendidos if p.get('monto_comision'))

                # Las comisiones se calculan aparte, no cambian
                total_comisiones_productos = sum(float(p['monto_comision']) for p in productos_vendidos if p.get('monto_comision'))
                cursor.execute("""SELECT SUM(c.monto_comision) as total FROM comisiones c JOIN venta_items vi ON c.venta_item_id = vi.id JOIN ventas v ON vi.venta_id = v.id WHERE c.colaborador_id = %s AND vi.servicio_id IS NOT NULL AND DATE(c.fecha_generacion) BETWEEN %s AND %s""", (colaborador_id, fecha_inicio, fecha_fin))
                comisiones_servicios = cursor.fetchone()
                total_comisiones_servicios = float(comisiones_servicios['total']) if comisiones_servicios and comisiones_servicios['total'] else 0.0
                total_comisiones_generadas = total_comisiones_productos + total_comisiones_servicios

                resultados = {
                    "servicios_vendidos": servicios_vendidos, 
                    "productos_vendidos": productos_vendidos,
                    "total_produccion_servicios": total_produccion_servicios,
                    "total_produccion_productos": total_produccion_productos,
                    "total_comisiones": total_comisiones
                }
                
        except mysql.connector.Error as err:
            flash(f"Error al generar el reporte de producción: {err}", "danger")
            current_app.logger.error(f"Error generando reporte de producción: {err}")
            resultados = None

    return render_template('reportes/reporte_produccion.html',
                           titulo_pagina="Reporte de Producción por Colaborador",
                           sucursales=sucursales,
                           colaboradores=colaboradores,
                           filtros=request.args,
                           resultados=resultados)

@main_bp.route('/reportes/produccion/exportar')
@login_required
@admin_required
def exportar_reporte_produccion():
    """
    Genera un archivo Excel con el reporte de producción y lo devuelve para su descarga.
    """
    db_conn = get_db()
    
    # Obtener los filtros de la URL (igual que en el reporte en pantalla)
    colaborador_id = request.args.get('colaborador_id', type=int)
    sucursal_id = request.args.get('sucursal_id', type=int)
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')

    if not all([colaborador_id, sucursal_id, fecha_inicio, fecha_fin]):
        flash("Faltan filtros para generar el reporte de exportación.", "warning")
        return redirect(url_for('main.reporte_produccion'))

    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Obtener nombre del colaborador para el nombre del archivo
            cursor.execute("SELECT nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
            colaborador = cursor.fetchone()
            nombre_colaborador = f"{colaborador['nombres']} {colaborador['apellidos']}"

            # Ejecutar las mismas consultas que en el reporte en pantalla
            # Consulta para SERVICIOS
            sql_servicios = """SELECT v.fecha_venta, cl.nombres as cliente_nombres, cl.apellidos as cliente_apellidos, s.nombre as servicio_nombre, vi.precio_unitario_venta, ca.nombre as campana_nombre, vi.es_trabajo_extra FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id JOIN servicios s ON vi.servicio_id = s.id LEFT JOIN clientes cl ON v.cliente_id = cl.id LEFT JOIN campanas ca ON v.campana_id = ca.id WHERE v.empleado_id = %s AND v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s ORDER BY v.fecha_venta DESC"""
            cursor.execute(sql_servicios, (colaborador_id, sucursal_id, fecha_inicio, fecha_fin))
            servicios_vendidos = cursor.fetchall()

            # Consulta para PRODUCTOS
            sql_productos = """SELECT v.fecha_venta, cl.nombres as cliente_nombres, cl.apellidos as cliente_apellidos, p.nombre as producto_nombre, m.nombre as marca_nombre, vi.cantidad, vi.precio_unitario_venta, vi.subtotal_item_neto, com.monto_comision FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id JOIN productos p ON vi.producto_id = p.id LEFT JOIN clientes cl ON v.cliente_id = cl.id LEFT JOIN marcas m ON p.marca_id = m.id LEFT JOIN comisiones com ON com.venta_item_id = vi.id WHERE v.empleado_id = %s AND v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s ORDER BY v.fecha_venta DESC"""
            cursor.execute(sql_productos, (colaborador_id, sucursal_id, fecha_inicio, fecha_fin))
            productos_vendidos = cursor.fetchall()
            
        # Crear DataFrames de pandas con los resultados
        df_servicios = pd.DataFrame(servicios_vendidos)
        df_productos = pd.DataFrame(productos_vendidos)

        # Renombrar columnas para que se vean bien en Excel
        if not df_servicios.empty:
            df_servicios.rename(columns={'fecha_venta': 'Fecha', 'cliente_nombres': 'Nombres Cliente', 'cliente_apellidos': 'Apellidos Cliente', 'servicio_nombre': 'Servicio', 'precio_unitario_venta': 'Precio', 'campana_nombre': 'Campaña', 'es_trabajo_extra': 'Es Extra'}, inplace=True)
        if not df_productos.empty:
            df_productos.rename(columns={'fecha_venta': 'Fecha', 'cliente_nombres': 'Nombres Cliente', 'cliente_apellidos': 'Apellidos Cliente', 'producto_nombre': 'Producto', 'marca_nombre': 'Marca', 'cantidad': 'Cantidad', 'precio_unitario_venta': 'P. Venta Unit.', 'subtotal_item_neto': 'Subtotal', 'monto_comision': 'Comisión'}, inplace=True)

        # Crear un archivo Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_servicios.to_excel(writer, sheet_name='Servicios Realizados', index=False)
            df_productos.to_excel(writer, sheet_name='Productos Vendidos', index=False)
        output.seek(0)
        
        # Preparar la respuesta para descargar el archivo
        sanitized_name = "".join([c for c in nombre_colaborador if c.isalpha() or c.isdigit() or c==' ']).rstrip()
        nombre_archivo = f"Reporte_Produccion_{sanitized_name}_{fecha_inicio}_a_{fecha_fin}.xlsx"
        
        return Response(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment;filename={nombre_archivo}"}
        )

    except Exception as e:
        flash(f"Error al generar el archivo Excel: {e}", "danger")
        current_app.logger.error(f"Error en exportar_reporte_produccion: {e}")
        return redirect(url_for('main.reporte_produccion', **request.args))


@main_bp.route('/reportes/produccion-general')
@login_required
@admin_required
def reporte_produccion_general():
    """
    Muestra un reporte de producción consolidado para todos los colaboradores
    de una sucursal en un período de tiempo.
    """
    db_conn = get_db()
    
    # Obtener los filtros de la URL
    sucursal_id = request.args.get('sucursal_id', type=int)
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')

    # Cargar sucursales para el menú desplegable
    sucursales = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al cargar sucursales: {err}", "danger")

    resultados = []
    totales_generales = {}
    if sucursal_id and fecha_inicio and fecha_fin:
        try:
            with db_conn.cursor(dictionary=True) as cursor:
                # Esta consulta obtiene la producción y comisiones agrupadas por colaborador
                sql = """
                    SELECT
                        e.id as colaborador_id,
                        e.nombre_display AS colaborador_nombre,
                        SUM(CASE WHEN vi.servicio_id IS NOT NULL THEN vi.valor_produccion ELSE 0 END) as produccion_servicios,
                        SUM(CASE WHEN vi.producto_id IS NOT NULL THEN vi.valor_produccion ELSE 0 END) as produccion_productos,
                        (SELECT SUM(c.monto_comision) FROM comisiones c JOIN venta_items vi_c ON c.venta_item_id = vi_c.id JOIN ventas v_c ON vi_c.venta_id = v_c.id WHERE v_c.empleado_id = e.id AND DATE(v_c.fecha_venta) BETWEEN %s AND %s) as total_comisiones
                    FROM ventas v
                    JOIN empleados e ON v.empleado_id = e.id
                    JOIN venta_items vi ON v.id = vi.venta_id
                    WHERE v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s
                      AND v.estado_pago != 'Anulado'
                    GROUP BY e.id, e.nombre_display
                    ORDER BY colaborador_nombre;
                """
                cursor.execute(sql, (fecha_inicio, fecha_fin, sucursal_id, fecha_inicio, fecha_fin))
                resultados = cursor.fetchall()
                
                # Calcular los totales generales para el resumen
                if resultados:
                    totales_generales = {
                        'total_servicios': sum(float(r['produccion_servicios']) for r in resultados),
                        'total_productos': sum(float(r['produccion_productos']) for r in resultados),
                        'total_produccion': sum(float(r['produccion_servicios']) + float(r['produccion_productos']) for r in resultados),
                        'total_comisiones': sum(float(r['total_comisiones'] or 0) for r in resultados)
                    }

        except mysql.connector.Error as err:
            flash(f"Error al generar el reporte de producción: {err}", "danger")

    return render_template('reportes/reporte_produccion_general.html',
                           titulo_pagina="Reporte de Producción General",
                           sucursales=sucursales,
                           filtros=request.args,
                           resultados=resultados,
                           totales=totales_generales)


@main_bp.route('/configuracion/roles')
@login_required
@admin_required # Solo un administrador puede gestionar roles
def listar_roles():
    """
    Muestra la lista de todos los roles de usuario definidos en el sistema.
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, descripcion FROM roles ORDER BY nombre")
            lista_de_roles = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los roles: {err}", "danger")
        current_app.logger.error(f"Error en listar_roles: {err}")
        lista_de_roles = []
        
    return render_template('configuracion/lista_roles.html', 
                           roles=lista_de_roles,
                           titulo_pagina="Gestión de Roles")

@main_bp.route('/configuracion/roles/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_rol():
    """
    Maneja la creación de un nuevo rol de usuario.
    """
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')

        if not nombre:
            flash('El nombre del rol es obligatorio.', 'warning')
        else:
            try:
                db = get_db()
                with db.cursor() as cursor:
                    cursor.execute("INSERT INTO roles (nombre, descripcion) VALUES (%s, %s)", (nombre, descripcion))
                    db.commit()
                    flash(f'Rol "{nombre}" creado exitosamente.', 'success')
                    return redirect(url_for('main.listar_roles'))
            except mysql.connector.Error as err:
                db.rollback()
                if err.errno == 1062: # Error de nombre de rol duplicado
                    flash(f'Error: El rol "{nombre}" ya existe.', 'danger')
                else:
                    flash(f'Error al crear el rol: {err}', 'danger')
        
        # Si hay error, volver al formulario de creación
        return redirect(url_for('main.nuevo_rol'))

    # Método GET: muestra la página con el formulario
    return render_template('configuracion/form_rol.html', 
                           es_nuevo=True, 
                           titulo_form="Crear Nuevo Rol",
                           action_url=url_for('main.nuevo_rol'))
    
@main_bp.route('/configuracion/roles/<int:rol_id>/permisos', methods=['GET'])
@login_required
@admin_required
def gestionar_permisos_rol(rol_id):
    """
    Muestra la página para asignar permisos a un rol específico.
    """
    db_conn = get_db()
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Obtener el rol que estamos editando
            cursor.execute("SELECT * FROM roles WHERE id = %s", (rol_id,))
            rol = cursor.fetchone()
            if not rol:
                flash("Rol no encontrado.", "warning")
                return redirect(url_for('main.listar_roles'))

            # Obtener TODOS los permisos disponibles en el sistema
            cursor.execute("SELECT * FROM permisos ORDER BY nombre")
            todos_los_permisos = cursor.fetchall()
            
            # Obtener los IDs de los permisos que este rol YA TIENE asignados
            cursor.execute("SELECT permiso_id FROM rol_permisos WHERE rol_id = %s", (rol_id,))
            # Creamos un set (conjunto) de IDs para una búsqueda más eficiente en la plantilla
            permisos_asignados_ids = {row['permiso_id'] for row in cursor.fetchall()}

    except mysql.connector.Error as err:
        flash(f"Error al cargar la página de permisos: {err}", "danger")
        return redirect(url_for('main.listar_roles'))
    
    return render_template('configuracion/gestionar_permisos_rol.html',
                           rol=rol,
                           todos_los_permisos=todos_los_permisos,
                           permisos_asignados_ids=permisos_asignados_ids,
                           titulo_pagina=f"Permisos para Rol: {rol['nombre']}")

@main_bp.route('/configuracion/roles/<int:rol_id>/permisos', methods=['POST'])
@login_required
@admin_required
def guardar_permisos_rol(rol_id):
    """
    Procesa el guardado de los permisos asignados a un rol.
    """
    # Obtener la lista de IDs de los permisos que se marcaron en el formulario
    permisos_seleccionados_ids = request.form.getlist('permiso_id')
    # Convertir los IDs de string a integer
    permisos_seleccionados_ids = [int(pid) for pid in permisos_seleccionados_ids]

    db_conn = get_db()
    try:
        with db_conn.cursor() as cursor:
            # Estrategia "borrar y volver a crear": es la más simple y segura.
            # 1. Borrar todos los permisos actuales para este rol.
            cursor.execute("DELETE FROM rol_permisos WHERE rol_id = %s", (rol_id,))

            # 2. Insertar los nuevos permisos seleccionados.
            if permisos_seleccionados_ids:
                sql_insert = "INSERT INTO rol_permisos (rol_id, permiso_id) VALUES (%s, %s)"
                # Crear una lista de tuplas para una inserción múltiple
                valores_a_insertar = [(rol_id, pid) for pid in permisos_seleccionados_ids]
                cursor.executemany(sql_insert, valores_a_insertar)
            
            db_conn.commit()
            flash("Permisos actualizados exitosamente.", "success")

    except mysql.connector.Error as err:
        db_conn.rollback()
        flash(f"Error de base de datos al guardar los permisos: {err}", "danger")

    return redirect(url_for('main.listar_roles'))


#Aplicacion WEB


@main_bp.route('/comandas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_comanda():
    """
    Maneja la visualización (GET) y el guardado (POST) de una nueva comanda.
    Versión final, unificada y definitiva.
    """
    db_conn = get_db()
    IGV_TASA = 0.18 

    # --- Lógica POST (cuando se envía el formulario) ---
    if request.method == 'POST':
        try:
            # 1. Recoger datos del formulario
            sucursal_id = request.form.get('sucursal_id', type=int)
            colaborador_id = request.form.get('colaborador_id', type=int)
            cliente_id_str = request.form.get('cliente_id')
            items_json_str = request.form.get('items_json')
            
            # 2. Validar datos
            errores = []
            if not all([sucursal_id, colaborador_id, cliente_id_str]):
                errores.append("Faltan datos del colaborador, sucursal o cliente.")
            
            cliente_receptor_id = int(cliente_id_str) if cliente_id_str and cliente_id_str != "0" else None
            if not cliente_receptor_id:
                errores.append("Debe seleccionar un cliente.")

            lista_items = json.loads(items_json_str or '[]')
            if not lista_items:
                errores.append("La comanda debe tener al menos un ítem.")
            
            if errores:
                raise ValueError("; ".join(errores))
            
            # 3. Calcular totales de la comanda
            subtotal_servicios = sum(int(i['cantidad']) * float(i['precio_unitario_venta']) for i in lista_items if i.get('tipo_item') == 'Servicio')
            subtotal_productos = sum(int(i['cantidad']) * float(i['precio_unitario_venta']) for i in lista_items if i.get('tipo_item') == 'Producto')
            monto_final = subtotal_servicios + subtotal_productos
            base_imponible = round(monto_final / (1 + IGV_TASA), 2)
            monto_impuestos = round(monto_final - base_imponible, 2)
            
            # 4. Guardar en BD dentro de una transacción
            with db_conn.cursor() as cursor:
                # Insertar la cabecera en la tabla 'ventas' con el nuevo estado
                # Para una comanda, el cliente que recibe y el que paga son el mismo.
                sql_venta = """
                    INSERT INTO ventas (sucursal_id, cliente_receptor_id, cliente_facturacion_id, empleado_id, fecha_venta, 
                                        estado_proceso, estado_pago, monto_final_venta, 
                                        subtotal_servicios, subtotal_productos, monto_impuestos)
                    VALUES (%s, %s, %s, %s, %s, 'En Comanda', 'Pendiente de Pago', %s, %s, %s, %s)
                """
                val_venta = (
                    sucursal_id, cliente_receptor_id, cliente_receptor_id, colaborador_id, datetime.now(), 
                    monto_final, subtotal_servicios, subtotal_productos, monto_impuestos
                )
                cursor.execute(sql_venta, val_venta)
                venta_id = cursor.lastrowid

                # Insertar los ítems en 'venta_items'
                for item in lista_items:
                    subtotal_item = float(item['cantidad']) * float(item['precio_unitario_venta'])
                    
                    sql_item = """
                        INSERT INTO venta_items (venta_id, servicio_id, producto_id, descripcion_item_venta, 
                                                 cantidad, precio_unitario_venta, subtotal_item_bruto, subtotal_item_neto, es_trabajo_extra, notas_item)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    val_item = (
                        venta_id,
                        item.get('item_id') if item['tipo_item'] == 'Servicio' else None,
                        item.get('item_id') if item['tipo_item'] == 'Producto' else None,
                        item['descripcion_item_venta'],
                        int(item['cantidad']),
                        float(item['precio_unitario_venta']),
                        subtotal_item,
                        subtotal_item,
                        bool(item.get('es_trabajo_extra', False)),
                        item.get('notas_item') # Guardar la nota del estilo
                    )
                    cursor.execute(sql_item, val_item)
            
            db_conn.commit()
            flash(f"Comanda #{venta_id} enviada a caja exitosamente.", "success")
            return redirect(url_for('main.nueva_comanda'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"No se pudo enviar la comanda. Error: {str(e)}", "warning")
            current_app.logger.error(f"Error procesando comanda: {e}")
            return redirect(url_for('main.nueva_comanda'))

    # --- Lógica GET (para mostrar el formulario) ---
    listas_para_form = { 'clientes': [], 'servicios': [], 'productos': [], 'estilos_catalogo': [] }
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, razon_social_nombres, apellidos FROM clientes WHERE tipo_documento != 'RUC' OR tipo_documento IS NULL ORDER BY razon_social_nombres, apellidos")
            listas_para_form['clientes'] = cursor.fetchall()
            cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['servicios'] = cursor.fetchall()
            cursor.execute("SELECT p.id, p.nombre, p.precio_venta, m.nombre AS marca_nombre FROM productos p LEFT JOIN marcas m ON p.marca_id = m.id WHERE p.activo = TRUE ORDER BY p.nombre, m.nombre")
            listas_para_form['productos'] = cursor.fetchall()
            cursor.execute("SELECT id, nombre FROM estilos WHERE activo = TRUE ORDER BY nombre")
            listas_para_form['estilos_catalogo'] = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar datos del formulario: {e}", "danger")

    return render_template('comandas/form_comanda.html',
                           titulo_form="Registrar Nueva Comanda",
                           action_url=url_for('main.nueva_comanda'),
                           **listas_para_form)
    
    
@main_bp.route('/ventas/comandas-pendientes')
@login_required
# En el futuro, podríamos limitar esto a roles de Cajero y Administrador
def listar_comandas_pendientes():
    """
    Muestra una lista de todas las ventas que están en estado 'En Comanda'
    para una sucursal específica.
    """
    db_conn = get_db()
    # Obtener la sucursal seleccionada de la URL
    sucursal_id_seleccionada = request.args.get('sucursal_id', type=int)
    
    sucursales = []
    comandas_pendientes = []

    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Siempre cargamos las sucursales para el selector
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()

            # Si se ha seleccionado una sucursal, buscar las comandas pendientes
            if sucursal_id_seleccionada:
                sql = """
                    SELECT 
                        v.id, v.fecha_venta, v.monto_final_venta,
                        e.nombre_display AS colaborador_nombre,
                        CONCAT(c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) AS cliente_nombre
                    FROM ventas v
                    JOIN empleados e ON v.empleado_id = e.id
                    LEFT JOIN clientes c ON v.cliente_receptor_id = c.id
                    WHERE v.estado_proceso = 'En Comanda' AND v.sucursal_id = %s
                    ORDER BY v.fecha_venta ASC
                """
                cursor.execute(sql, (sucursal_id_seleccionada,))
                comandas_pendientes = cursor.fetchall()
    
    except mysql.connector.Error as err:
        flash(f"Error al cargar las comandas pendientes: {err}", "danger")
        current_app.logger.error(f"Error en listar_comandas_pendientes: {err}")

    return render_template('ventas/comandas_pendientes.html',
                           titulo_pagina="Comandas Pendientes de Cobro",
                           sucursales=sucursales,
                           sucursal_seleccionada_id=sucursal_id_seleccionada,
                           comandas=comandas_pendientes)
    

@main_bp.route('/configuracion/bonos')
@login_required
@admin_required
def listar_bonos():
    """
    Muestra la lista de todos los bonos e incentivos configurados.
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM bonos ORDER BY nombre")
            lista_de_bonos = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los bonos: {err}", "danger")
        lista_de_bonos = []
        
    return render_template('bonos/lista_bonos.html', 
                           bonos=lista_de_bonos,
                           titulo_pagina="Gestión de Bonos e Incentivos")

@main_bp.route('/configuracion/bonos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_bono():
    """
    Maneja la creación de un nuevo bono.
    """
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        monto_bono_str = request.form.get('monto_bono')
        activo = 'activo' in request.form

        if not nombre or not monto_bono_str:
            flash('El nombre y el monto del bono son obligatorios.', 'warning')
        else:
            try:
                monto_bono = float(monto_bono_str)
                db = get_db()
                with db.cursor() as cursor:
                    sql = "INSERT INTO bonos (nombre, descripcion, monto_bono, activo) VALUES (%s, %s, %s, %s)"
                    cursor.execute(sql, (nombre, descripcion, monto_bono, activo))
                    db.commit()
                    flash(f'Bono "{nombre}" creado exitosamente.', 'success')
                    return redirect(url_for('main.listar_bonos'))
            except mysql.connector.Error as err:
                db.rollback()
                flash(f'Error al crear el bono: {err}', 'danger')
        
        return redirect(url_for('main.nuevo_bono'))

    return render_template('bonos/form_bono.html', 
                           es_nuevo=True, 
                           titulo_form="Crear Nuevo Bono",
                           action_url=url_for('main.nuevo_bono'))    


@main_bp.route('/configuracion/bonos/<int:bono_id>/reglas', methods=['GET'])
@login_required
@admin_required
def gestionar_reglas_bono(bono_id):
    """
    Muestra la página para ver y añadir reglas a un bono específico.
    """
    db_conn = get_db()
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Obtener datos del bono para mostrar su nombre
            cursor.execute("SELECT * FROM bonos WHERE id = %s", (bono_id,))
            bono = cursor.fetchone()
            if not bono:
                flash("Bono no encontrado.", "warning")
                return redirect(url_for('main.listar_bonos'))

            # Obtener las reglas ya registradas para este bono
            cursor.execute("""
                SELECT br.*, s.nombre as servicio_nombre 
                FROM bono_reglas br 
                LEFT JOIN servicios s ON br.servicio_id_asociado = s.id
                WHERE br.bono_id = %s ORDER BY br.id
            """, (bono_id,))
            reglas_registradas = cursor.fetchall()
            
            # Cargar todos los servicios para el desplegable del formulario
            cursor.execute("SELECT id, nombre FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_disponibles = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al cargar la página de reglas: {err}", "danger")
        return redirect(url_for('main.listar_bonos'))

    # Tipos de reglas que nuestro sistema soporta
    tipos_regla_opciones = {
        'PRODUCCION_SERVICIOS': 'Producción Total en Servicios',
        'SUMA_COMISION_PRODUCTOS': 'Suma de Comisión por Productos',
        'CANTIDAD_SERVICIO': 'Cantidad de un Servicio Específico Vendido',
        'CANTIDAD_MEMBRESIA': 'Cantidad de Membresías Vendidas'
    }
        
    return render_template('bonos/gestionar_reglas.html',
                           bono=bono,
                           reglas=reglas_registradas,
                           servicios_disponibles=servicios_disponibles,
                           tipos_regla=tipos_regla_opciones,
                           titulo_pagina=f"Reglas para Bono: {bono['nombre']}")

@main_bp.route('/configuracion/bonos/<int:bono_id>/reglas/nueva', methods=['POST'])
@login_required
@admin_required
def agregar_regla_bono(bono_id):
    """
    Procesa el formulario para añadir una nueva regla a un bono.
    """
    tipo_regla = request.form.get('tipo_regla')
    operador = request.form.get('operador')
    valor_objetivo_str = request.form.get('valor_objetivo')
    servicio_id_asociado_str = request.form.get('servicio_id_asociado')

    if not all([tipo_regla, operador, valor_objetivo_str]):
        flash("Todos los campos son obligatorios para crear una regla.", "warning")
        return redirect(url_for('main.gestionar_reglas_bono', bono_id=bono_id))

    try:
        valor_objetivo = float(valor_objetivo_str)
        servicio_id_asociado = int(servicio_id_asociado_str) if servicio_id_asociado_str else None
        
        # Validación extra
        if tipo_regla == 'CANTIDAD_SERVICIO' and not servicio_id_asociado:
            raise ValueError("Debe seleccionar un servicio para la regla 'Cantidad de Servicio'.")

        db = get_db()
        with db.cursor() as cursor:
            sql = "INSERT INTO bono_reglas (bono_id, tipo_regla, operador, valor_objetivo, servicio_id_asociado) VALUES (%s, %s, %s, %s, %s)"
            cursor.execute(sql, (bono_id, tipo_regla, operador, valor_objetivo, servicio_id_asociado))
            db.commit()
            flash("Regla añadida exitosamente.", "success")
    except (ValueError, mysql.connector.Error) as e:
        get_db().rollback()
        flash(f"Error al guardar la regla: {e}", "danger")
    
    return redirect(url_for('main.gestionar_reglas_bono', bono_id=bono_id))


@main_bp.route('/configuracion/bonos/reglas/eliminar/<int:regla_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_regla_bono(regla_id):
    """
    Elimina una regla específica de un bono.
    """
    db = get_db()
    bono_id_para_redirigir = None
    try:
        with db.cursor(dictionary=True) as cursor:
            # Primero, obtenemos el bono_id para saber a dónde volver
            cursor.execute("SELECT bono_id FROM bono_reglas WHERE id = %s", (regla_id,))
            regla = cursor.fetchone()
            if regla:
                bono_id_para_redirigir = regla['bono_id']
                
                # Ahora, eliminamos la regla
                cursor.execute("DELETE FROM bono_reglas WHERE id = %s", (regla_id,))
                db.commit()
                flash("Regla eliminada exitosamente.", "success")
            else:
                flash("La regla que intentas eliminar no fue encontrada.", "warning")

    except mysql.connector.Error as err:
        db.rollback()
        flash(f"Error al eliminar la regla: {err}", "danger")

    if bono_id_para_redirigir:
        return redirect(url_for('main.gestionar_reglas_bono', bono_id=bono_id_para_redirigir))
    else:
        # Si algo falla, volver a la lista general de bonos
        return redirect(url_for('main.listar_bonos'))

@main_bp.route('/configuracion/membresias')
@login_required
@admin_required
def listar_planes_membresia():
    """
    Muestra la lista de todos los planes de membresía definidos.
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM membresia_planes ORDER BY nombre")
            planes = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los planes de membresía: {err}", "danger")
        current_app.logger.error(f"Error en listar_planes_membresia: {err}")
        planes = []
        
    return render_template('membresias/lista_planes.html', 
                           planes=planes,
                           titulo_pagina="Planes de Membresía")



@main_bp.route('/configuracion/membresias/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_plan_membresia():
    db_conn = get_db()
    
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            precio = request.form.get('precio', type=float)
            duracion_dias = request.form.get('duracion_dias', type=int)
            # CORRECCIÓN: Leer el valor del checkbox correctamente
            activo = 'activo' in request.form
            beneficios_json_str = request.form.get('beneficios_json')

            if not all([nombre, precio is not None, duracion_dias is not None]):
                raise ValueError("Nombre, Precio y Duración son campos obligatorios.")
            
            lista_beneficios = json.loads(beneficios_json_str or '[]')
            if not lista_beneficios:
                raise ValueError("Un plan debe tener al menos un servicio como beneficio.")

            with db_conn.cursor() as cursor:
                sql_plan = "INSERT INTO membresia_planes (nombre, descripcion, precio, duracion_dias, activo) VALUES (%s, %s, %s, %s, %s)"
                cursor.execute(sql_plan, (nombre, (descripcion or None), precio, duracion_dias, activo))
                nuevo_plan_id = cursor.lastrowid

                sql_beneficio = "INSERT INTO membresia_plan_beneficios (plan_id, servicio_id, cantidad_incluida, precio_en_paquete) VALUES (%s, %s, %s, %s)"
                valores_beneficios = [(nuevo_plan_id, int(b['servicio_id']), int(b['cantidad']), float(b['precio_en_paquete'])) for b in lista_beneficios]
                cursor.executemany(sql_beneficio, valores_beneficios)
            
            db_conn.commit()
            flash(f'Plan de membresía "{nombre}" creado exitosamente.', 'success')
            return redirect(url_for('main.listar_planes_membresia'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"Error al crear el plan: {e}", "danger")
    
    # Lógica GET (sin cambios)
    servicios_disponibles = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_disponibles = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar la lista de servicios: {e}", "danger")

    return render_template('membresias/form_plan.html', 
                           es_nueva=True, 
                           titulo_form="Crear Nuevo Plan de Membresía",
                           action_url=url_for('main.nuevo_plan_membresia'),
                           servicios_disponibles=servicios_disponibles,
                           plan={},
                           form_data=request.form if request.method == 'POST' else None)
    

@main_bp.route('/configuracion/membresias/editar/<int:plan_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_plan_membresia(plan_id):
    """
    Maneja la edición de un plan de membresía existente y sus beneficios.
    Versión final y completa.
    """
    db_conn = get_db()
    
    # --- Lógica POST (cuando se guarda el formulario de edición) ---
    if request.method == 'POST':
        try:
            # 1. Recoger todos los datos del formulario
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            precio = request.form.get('precio', type=float)
            duracion_dias = request.form.get('duracion_dias', type=int)
            activo = 'activo' in request.form
            beneficios_json_str = request.form.get('beneficios_json')

            # 2. Validaciones
            if not all([nombre, precio is not None, duracion_dias is not None]):
                raise ValueError("Nombre, Precio y Duración son campos obligatorios.")
            
            lista_beneficios = json.loads(beneficios_json_str or '[]')
            if not lista_beneficios:
                raise ValueError("Un plan debe tener al menos un servicio como beneficio.")

            # 3. Guardar en la Base de Datos (Transacción)
            with db_conn.cursor() as cursor:
                # 3a. Actualizar la tabla principal 'membresia_planes'
                sql_update_plan = """UPDATE membresia_planes SET 
                                        nombre=%s, descripcion=%s, precio=%s, 
                                        duracion_dias=%s, activo=%s 
                                     WHERE id=%s"""
                cursor.execute(sql_update_plan, (nombre, (descripcion or None), precio, duracion_dias, activo, plan_id))
                
                # 3b. Borrar los beneficios antiguos para reemplazarlos con la nueva lista
                cursor.execute("DELETE FROM membresia_plan_beneficios WHERE plan_id = %s", (plan_id,))

                # 3c. Insertar los nuevos beneficios (si hay alguno)
                if lista_beneficios:
                    sql_insert_beneficios = "INSERT INTO membresia_plan_beneficios (plan_id, servicio_id, cantidad_incluida, precio_en_paquete) VALUES (%s, %s, %s, %s)"
                    valores_beneficios = [(plan_id, int(b['servicio_id']), int(b['cantidad']), float(b['precio_en_paquete'])) for b in lista_beneficios]
                    cursor.executemany(sql_insert_beneficios, valores_beneficios)
            
            db_conn.commit()
            flash(f'Plan de membresía "{nombre}" actualizado exitosamente.', 'success')
            return redirect(url_for('main.listar_planes_membresia'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"Error al actualizar el plan: {e}", "danger")
            # En caso de error, volver a la misma página de edición
            return redirect(url_for('main.editar_plan_membresia', plan_id=plan_id))

    # --- Lógica GET (para mostrar el formulario con datos existentes) ---
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Obtener el plan
            cursor.execute("SELECT * FROM membresia_planes WHERE id = %s", (plan_id,))
            plan_actual = cursor.fetchone()
            if not plan_actual:
                flash("Plan no encontrado.", "warning")
                return redirect(url_for('main.listar_planes_membresia'))

            # Obtener los beneficios actuales de este plan
            cursor.execute("""
                SELECT 
                    mb.servicio_id, 
                    mb.cantidad_incluida AS cantidad, 
                    mb.precio_en_paquete, 
                    s.nombre AS servicio_nombre 
                FROM membresia_plan_beneficios mb 
                JOIN servicios s ON mb.servicio_id = s.id 
                WHERE mb.plan_id = %s
            """, (plan_id,))
            beneficios_actuales = cursor.fetchall()
            
            # Obtener todos los servicios disponibles para el desplegable
            cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_disponibles = cursor.fetchall()

    except Exception as e:
        flash(f"Error al cargar los datos del plan: {e}", "danger")
        return redirect(url_for('main.listar_planes_membresia'))

    return render_template('membresias/form_plan.html',
                           es_nueva=False,
                           titulo_form=f"Editar Plan: {plan_actual['nombre']}",
                           action_url=url_for('main.editar_plan_membresia', plan_id=plan_id),
                           plan=plan_actual,
                           beneficios_json=json.dumps(beneficios_actuales, default=str),
                           servicios_disponibles=servicios_disponibles)
    

@main_bp.route('/configuracion/membresias/toggle-activo/<int:plan_id>')
@login_required
@admin_required
def toggle_activo_plan_membresia(plan_id):
    """
    Activa o desactiva un plan de membresía.
    """
    db = get_db()
    try:
        with db.cursor(dictionary=True) as cursor:
            # Primero, obtenemos el estado actual del plan
            cursor.execute("SELECT activo, nombre FROM membresia_planes WHERE id = %s", (plan_id,))
            plan = cursor.fetchone()
            
            if plan:
                # Invertimos el estado actual (si era True, se vuelve False, y viceversa)
                nuevo_estado = not plan['activo']
                cursor.execute("UPDATE membresia_planes SET activo = %s WHERE id = %s", (nuevo_estado, plan_id))
                db.commit()
                estado_texto = "activado" if nuevo_estado else "desactivado"
                flash(f"El plan '{plan['nombre']}' ha sido {estado_texto} exitosamente.", "success")
            else:
                flash("Plan de membresía no encontrado.", "warning")

    except mysql.connector.Error as err:
        db.rollback()
        flash(f"Error al cambiar el estado del plan: {err}", "danger")

    return redirect(url_for('main.listar_planes_membresia'))

    
@main_bp.route('/api/clientes/<int:cliente_id>/creditos')
@login_required
def api_get_creditos_cliente(cliente_id):
    """
    API para obtener los créditos de servicios disponibles de la membresía activa de un cliente.
    """
    if cliente_id == 0:
        return jsonify([]) # Cliente Varios no tiene créditos

    db_conn = get_db()
    creditos_disponibles = []
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # Esta consulta busca los créditos de una membresía que esté 'Activa'
            # y cuya fecha de hoy esté dentro de su período de vigencia.
            # También calcula los créditos restantes.
            sql = """
                SELECT 
                    cmc.id as credito_id,
                    cmc.servicio_id,
                    s.nombre AS servicio_nombre,
                    (cmc.cantidad_total - cmc.cantidad_usada) AS cantidad_restante
                FROM cliente_membresia_creditos cmc
                JOIN cliente_membresias cm ON cmc.cliente_membresia_id = cm.id
                JOIN servicios s ON cmc.servicio_id = s.id
                WHERE 
                    cm.cliente_id = %s 
                    AND cm.estado = 'Activa' 
                    AND CURDATE() BETWEEN cm.fecha_inicio AND cm.fecha_fin
                    AND (cmc.cantidad_total - cmc.cantidad_usada) > 0
            """
            cursor.execute(sql, (cliente_id,))
            creditos_disponibles = cursor.fetchall()
            
            # Convertir los valores Decimal a int si es necesario (depende de tu conector)
            for credito in creditos_disponibles:
                credito['cantidad_restante'] = int(credito['cantidad_restante'])

    except mysql.connector.Error as err:
        current_app.logger.error(f"Error DB en api_get_creditos_cliente (ID: {cliente_id}): {err}")
        return jsonify({"error": "Error interno al consultar los créditos del cliente."}), 500

    return jsonify(creditos_disponibles)


@main_bp.route('/reportes/liquidacion/pagar', methods=['POST'])
@login_required
@admin_required
def pagar_liquidacion():
    """
    Procesa el pago de una liquidación mensual para un colaborador.
    1. Recalcula todos los montos para verificar.
    2. Actualiza los estados de comisiones y ajustes.
    3. Registra un gasto por el pago total.
    4. Crea un registro histórico en la tabla 'liquidaciones'.
    """
    db_conn = get_db()
    
    # 1. Recoger todos los datos del formulario
    colaborador_id = request.form.get('colaborador_id', type=int)
    anio = request.form.get('anio', type=int)
    mes = request.form.get('mes', type=int)
    liquido_pagado_form = request.form.get('liquido_a_pagar', type=float)
    metodo_pago_liquidacion = request.form.get('metodo_pago_liquidacion')
    comisiones_ids = request.form.getlist('comision_id')
    ajustes_ids = request.form.getlist('ajuste_id')
    registrado_por_id = current_user.id
    
    # URL de redirección en caso de éxito o error
    redirect_url = url_for('main.reporte_liquidacion', colaborador_id=colaborador_id, anio=anio, mes=mes)

    if not all([colaborador_id, anio, mes, metodo_pago_liquidacion]):
        flash("Faltan datos para procesar la liquidación.", "warning")
        return redirect(redirect_url)

    try:
        # Usamos 'with' para que el cursor se cierre automáticamente
        with db_conn.cursor(dictionary=True) as cursor:
            # La transacción se inicia implícitamente con la primera operación de escritura
            
            # 2. Recalcular todos los montos en el servidor para verificar
            cursor.execute("SELECT nombres, apellidos, sueldo_base, sucursal_id FROM empleados WHERE id = %s", (colaborador_id,))
            colaborador_info = cursor.fetchone()
            if not colaborador_info: raise ValueError("Colaborador no encontrado.")
            
            sueldo_base = float(colaborador_info.get('sueldo_base', 0.0))
            sucursal_id_colaborador = colaborador_info.get('sucursal_id')

            _, num_dias_mes = calendar.monthrange(anio, mes)
            fecha_inicio_periodo = date(anio, mes, 1)
            fecha_fin_periodo = date(anio, mes, num_dias_mes)

            cursor.execute("SELECT monto_cuota FROM cuotas_mensuales WHERE colaborador_id = %s AND anio = %s AND mes = %s", (colaborador_id, anio, mes))
            cuota_obj = cursor.fetchone()
            monto_cuota = float(cuota_obj['monto_cuota']) if cuota_obj else 0.0
            
            cursor.execute("SELECT SUM(vi.valor_produccion) as total FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id WHERE v.empleado_id = %s AND v.estado_pago != 'Anulado' AND DATE(v.fecha_venta) BETWEEN %s AND %s AND (vi.producto_id IS NOT NULL OR (vi.servicio_id IS NOT NULL AND vi.es_trabajo_extra = FALSE))", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
            produccion = cursor.fetchone()
            total_produccion = float(produccion['total'] or 0.0)
            bono_produccion = max(0, (total_produccion - monto_cuota) * 0.50)

            total_comisiones, total_otros_bonos, total_descuentos = 0.0, 0.0, 0.0
            if comisiones_ids:
                format_strings_com = ','.join(['%s'] * len(comisiones_ids))
                cursor.execute(f"SELECT SUM(monto_comision) as total FROM comisiones WHERE id IN ({format_strings_com}) AND estado = 'Pendiente'", tuple(comisiones_ids))
                total_comisiones = float(cursor.fetchone()['total'] or 0.0)
            
            if ajustes_ids:
                format_strings_aj = ','.join(['%s'] * len(ajustes_ids))
                cursor.execute(f"SELECT monto FROM ajustes_pago WHERE id IN ({format_strings_aj}) AND estado = 'Pendiente'", tuple(ajustes_ids))
                ajustes_a_pagar = cursor.fetchall()
                total_otros_bonos = sum(float(a['monto']) for a in ajustes_a_pagar if a['monto'] > 0)
                total_descuentos = abs(sum(float(a['monto']) for a in ajustes_a_pagar if a['monto'] < 0))

            liquido_a_pagar_calculado = (sueldo_base + bono_produccion + total_comisiones + total_otros_bonos) - total_descuentos
            
            if abs(liquido_a_pagar_calculado - liquido_pagado_form) > 0.01:
                raise ValueError("El monto total de la liquidación ha cambiado. Por favor, genere el reporte de nuevo.")

            # 3. Registrar el Gasto
            cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Sueldos y Planilla'")
            cat_gasto = cursor.fetchone()
            categoria_gasto_id = cat_gasto['id'] if cat_gasto else None
            if not categoria_gasto_id: 
                cursor.execute("INSERT INTO categorias_gastos (nombre, descripcion) VALUES ('Sueldos y Planilla', 'Pagos de liquidaciones a colaboradores')")
                categoria_gasto_id = cursor.lastrowid
            
            descripcion_gasto = f"Pago de liquidación a {colaborador_info['nombres']} {colaborador_info['apellidos']} por el período {mes}/{anio}."
            sql_gasto = "INSERT INTO gastos (sucursal_id, categoria_gasto_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            val_gasto = (sucursal_id_colaborador, categoria_gasto_id, date.today(), descripcion_gasto, liquido_a_pagar_calculado, metodo_pago_liquidacion, registrado_por_id)
            cursor.execute(sql_gasto, val_gasto)
            gasto_id = cursor.lastrowid
            
            # 4. Actualizar estados
            if comisiones_ids:
                cursor.execute(f"UPDATE comisiones SET estado = 'Pagada', fecha_pago = NOW() WHERE id IN ({format_strings_com})", tuple(comisiones_ids))
            if ajustes_ids:
                cursor.execute(f"UPDATE ajustes_pago SET estado = 'Aplicado en Liquidación' WHERE id IN ({format_strings_aj})", tuple(ajustes_ids))

            # 5. Guardar el registro histórico en 'liquidaciones'
            sql_liquidacion = "INSERT INTO liquidaciones (colaborador_id, anio, mes, fecha_pago, monto_sueldo_base, monto_bono_produccion, monto_total_comisiones, monto_total_otros_ingresos, monto_total_descuentos, monto_liquido_pagado, gasto_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            val_liquidacion = (colaborador_id, anio, mes, datetime.now(), sueldo_base, bono_produccion, total_comisiones, total_otros_bonos, total_descuentos, liquido_a_pagar_calculado, gasto_id)
            cursor.execute(sql_liquidacion, val_liquidacion)
        
        db_conn.commit()
        flash(f"Liquidación para el período {mes}/{anio} registrada y marcada como pagada exitosamente.", "success")

    except (ValueError, mysql.connector.Error, Exception) as e:
        if db_conn and db_conn.in_transaction: db_conn.rollback()
        flash(f"No se pudo registrar el pago de la liquidación. Error: {str(e)}", "danger")
        current_app.logger.error(f"Error en pagar_liquidacion: {e}")

    return redirect(redirect_url)

# En app/routes.py

@main_bp.route('/clientes/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def importar_clientes():
    """
    Maneja la carga de un archivo Excel para la importación masiva de clientes,
    adaptado a la nueva estructura de la tabla clientes.
    """
    if request.method == 'POST':
        if 'archivo_excel' not in request.files:
            flash('No se encontró el archivo en la solicitud.', 'danger')
            return redirect(request.url)
        
        archivo = request.files['archivo_excel']
        if archivo.filename == '':
            flash('No se seleccionó ningún archivo.', 'warning')
            return redirect(request.url)

        if archivo and (archivo.filename.endswith('.xlsx') or archivo.filename.endswith('.xls')):
            try:
                df = pd.read_excel(archivo, dtype=str).fillna('')
                
                # Columnas requeridas actualizadas
                columnas_requeridas = ['TipoDocumento', 'NumeroDocumento', 'RazonSocialNombres']
                if not all(col in df.columns for col in columnas_requeridas):
                    flash(f"El archivo debe contener, como mínimo, las columnas: {', '.join(columnas_requeridas)}.", 'danger')
                    return redirect(request.url)

                clientes_a_insertar = []
                for index, row in df.iterrows():
                    # Validar que los campos requeridos no estén vacíos en esta fila
                    if not all([row.get('TipoDocumento'), row.get('NumeroDocumento'), row.get('RazonSocialNombres')]):
                        continue # Saltar esta fila si le falta un dato obligatorio

                    tipo_doc = str(row['TipoDocumento']).strip().upper()
                    apellidos = str(row.get('Apellidos', '')) or None
                    if tipo_doc == 'RUC':
                        apellidos = None # Las empresas no tienen apellidos

                    cliente_data = {
                        'tipo_documento': tipo_doc,
                        'numero_documento': str(row['NumeroDocumento']).strip(),
                        'razon_social_nombres': str(row['RazonSocialNombres']).strip(),
                        'apellidos': apellidos,
                        'direccion': str(row.get('Direccion', '')) or None,
                        'email': str(row.get('Email', '')) or None,
                        'telefono': str(row.get('Telefono', '')).strip().replace(' ', '') or None,
                        'fecha_nacimiento': pd.to_datetime(row.get('FechaNacimiento'), errors='coerce').date() if pd.notna(row.get('FechaNacimiento')) else None
                    }
                    clientes_a_insertar.append(tuple(cliente_data.values()))

                if not clientes_a_insertar:
                    flash("No se encontraron filas válidas para importar en el archivo.", "warning")
                    return redirect(request.url)
                
                db = get_db()
                with db.cursor() as cursor:
                    # INSERT IGNORE usará la restricción UNIQUE del numero_documento para evitar duplicados
                    sql = "INSERT IGNORE INTO clientes (tipo_documento, numero_documento, razon_social_nombres, apellidos, direccion, email, telefono, fecha_nacimiento) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                    cursor.executemany(sql, clientes_a_insertar)
                    db.commit()
                    flash(f"Importación completada. Se insertaron {cursor.rowcount} nuevos clientes. Se ignoraron {len(clientes_a_insertar) - cursor.rowcount} registros por duplicados (basado en el número de documento).", "success")

                return redirect(url_for('main.listar_clientes'))

            except Exception as e:
                flash(f"Ocurrió un error al procesar el archivo: {e}", "danger")
                current_app.logger.error(f"Error importando clientes: {e}")
                return redirect(request.url)
        else:
            flash('Formato de archivo no válido. Por favor, suba un archivo .xlsx o .xls', 'warning')
            return redirect(request.url)

    return render_template('clientes/importar_clientes.html', 
                           titulo_pagina="Importar Clientes desde Excel")


@main_bp.route('/membresias/clientes')
@login_required
@admin_required # Solo un administrador puede ver este reporte
def listar_cliente_membresias():
    """
    Muestra una lista de todas las membresías adquiridas por los clientes.
    Calcula el estado (Activa/Expirada) al momento de la consulta.
    """
    db_conn = get_db()
    
    # Obtener el filtro de estado de la URL, por defecto mostrará 'Activa'
    filtro_estado = request.args.get('filtro_estado', 'Activa')
    
    lista_membresias = []
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # La consulta base une las 3 tablas necesarias
            sql_base = """
                SELECT 
                    cm.id,
                    CONCAT(c.razon_social_nombres, ' ', IFNULL(c.apellidos, '')) AS cliente_nombre,
                    mp.nombre AS plan_nombre,
                    cm.fecha_inicio,
                    cm.fecha_fin,
                    CASE
                        WHEN CURDATE() > cm.fecha_fin THEN 'Expirada'
                        ELSE 'Activa'
                    END AS estado_calculado
                FROM cliente_membresias cm
                JOIN clientes c ON cm.cliente_id = c.id
                JOIN membresia_planes mp ON cm.plan_id = mp.id
            """
            
            params = []
            where_clauses = []
            
            # Aplicar filtro de estado si no es 'Todas'
            if filtro_estado != 'Todas':
                if filtro_estado == 'Expirada':
                    where_clauses.append("(cm.estado = 'Expirada' OR (cm.estado = 'Activa' AND cm.fecha_fin < CURDATE()))")
                else: # Para 'Activa' y otros futuros estados
                    where_clauses.append("cm.estado = %s AND cm.fecha_fin >= CURDATE()")
                    params.append(filtro_estado)
            
            if where_clauses:
                sql_base += " WHERE " + " AND ".join(where_clauses)

            sql_base += " ORDER BY cm.fecha_fin ASC"
            
            cursor.execute(sql_base, tuple(params))
            lista_membresias = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Error al acceder a las membresías de clientes: {err}", "danger")
        current_app.logger.error(f"Error en listar_cliente_membresias: {err}")

    return render_template('membresias/lista_cliente_membresias.html',
                           membresias=lista_membresias,
                           filtro_actual=filtro_estado,
                           titulo_pagina="Membresías de Clientes")


@main_bp.route('/configuracion/facturacion', methods=['GET', 'POST'])
@login_required
@admin_required
def configurar_facturacion():
    instance_path = current_app.instance_path
    certs_path = os.path.join(instance_path, 'certs')
    credentials_file_path = os.path.join(instance_path, 'sunat_credentials.json')
    os.makedirs(certs_path, exist_ok=True)

    if request.method == 'POST':
        try:
            # Guardar el Certificado
            if 'certificado_digital' in request.files:
                archivo = request.files['certificado_digital']
                if archivo and archivo.filename != '':
                    nombre_seguro = secure_filename("certificado_sunat.pfx")
                    archivo.save(os.path.join(certs_path, nombre_seguro))
                    flash('Certificado digital guardado exitosamente.', 'success')

            # Guardar las Credenciales, incluyendo el RUC
            credenciales = {
                'emisor_ruc': request.form.get('emisor_ruc'),
                'password_certificado': request.form.get('password_certificado'),
                'usuario_sol': request.form.get('usuario_sol'),
                'clave_sol': request.form.get('clave_sol')
            }
            with open(credentials_file_path, 'w') as f:
                json.dump(credenciales, f)
            flash('Configuración de facturación guardada exitosamente.', 'success')
            return redirect(url_for('main.configurar_facturacion'))
        except Exception as e:
            flash(f"Ocurrió un error al guardar la configuración: {e}", 'danger')

    # Lógica GET
    certificado_existente = os.path.exists(os.path.join(certs_path, "certificado_sunat.pfx"))
    credenciales_existentes = {}
    if os.path.exists(credentials_file_path):
        with open(credentials_file_path, 'r') as f:
            credenciales_existentes = json.load(f)

    return render_template('configuracion/form_facturacion.html',
                           titulo_pagina="Configuración de Facturación Electrónica",
                           certificado_existente=certificado_existente,
                           credenciales=credenciales_existentes)


def _generar_y_firmar_xml(venta_id):
    """
    Función interna que genera y firma el XML para una venta.
    Devuelve el string del XML firmado y el nombre base del archivo.
    """
    db_conn = get_db()
    
    # --- 1. Cargar Todos los Datos Necesarios de la BD ---
    with db_conn.cursor(dictionary=True) as cursor:
        # Datos de la venta, sucursal, etc.
        sql_venta = "SELECT v.*, s.nombre AS sucursal_nombre FROM ventas v JOIN sucursales s ON v.sucursal_id = s.id WHERE v.id = %s"
        cursor.execute(sql_venta, (venta_id,))
        venta = cursor.fetchone()
        if not venta:
            raise ValueError("Venta no encontrada.")
        
        # Datos del cliente (o datos genéricos si no hay cliente de facturación)
        cliente = {}
        if venta.get('cliente_facturacion_id'):
            cursor.execute("SELECT * FROM clientes WHERE id = %s", (venta['cliente_facturacion_id'],))
            cliente = cursor.fetchone()
        
        if not cliente:
            cliente = {'tipo_documento': 'Otro', 'numero_documento': '00000000', 'razon_social_nombres': 'CLIENTES', 'apellidos': 'VARIOS'}

        # Datos de los ítems de la venta
        cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,))
        items = cursor.fetchall()
        if not items:
            raise ValueError("La venta no tiene ítems.")

    # --- 2. Cargar Certificado y Credenciales ---
    instance_path = current_app.instance_path
    certs_path = os.path.join(instance_path, 'certs', 'certificado_sunat.pfx')
    credentials_file_path = os.path.join(instance_path, 'sunat_credentials.json')
    
    if not os.path.exists(certs_path) or not os.path.exists(credentials_file_path):
        raise ValueError("No se ha configurado el Certificado Digital o las credenciales SUNAT.")
    
    with open(credentials_file_path, 'r') as f:
        credenciales = json.load(f)
    
    password_certificado = credenciales.get('password_certificado')
    if not password_certificado:
        raise ValueError("La contraseña del certificado no está configurada.")
    
    with open(certs_path, 'rb') as pfx_file:
        pfx_data = pfx_file.read()
    
    private_key, public_cert, additional_certs = pkcs12.load_key_and_certificates(
        pfx_data, 
        password_certificado.encode('utf-8')
    )
    
    # --- FIN PARTE 1 ---
    # --- INICIO PARTE 2: Construcción de la Estructura XML ---

    # 2a. Definir los namespaces (un estándar requerido por SUNAT)
    NS_MAP = {
        None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        "ds": "http://www.w3.org/2000/09/xmldsig#"
    }
    
    # Crear el elemento raíz del XML. Para Boletas y Facturas se usa "Invoice".
    invoice = ET.Element("Invoice", nsmap=NS_MAP)
    
    # UBLExtensions: Un contenedor que es requerido y que contendrá la firma digital
    ubl_extensions = ET.SubElement(invoice, ET.QName(NS_MAP["ext"], "UBLExtensions"))
    signature_extension = ET.SubElement(ubl_extensions, ET.QName(NS_MAP["ext"], "UBLExtension"))
    ET.SubElement(signature_extension, ET.QName(NS_MAP["ext"], "ExtensionContent"))

    # 2b. Información General del Comprobante
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "UBLVersionID")).text = "2.1"
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "CustomizationID")).text = "2.0"
    
    comprobante_id = f"{venta.get('serie_comprobante')}-{venta.get('numero_comprobante')}"
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "ID")).text = comprobante_id
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "IssueDate")).text = venta['fecha_venta'].strftime('%Y-%m-%d')
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "IssueTime")).text = venta['fecha_venta'].strftime('%H:%M:%S')
    
    # Tipo de Comprobante: 01 para Factura, 03 para Boleta
    tipo_doc_map = { 'Boleta Electrónica': '03', 'Factura Electrónica': '01' }
    tipo_documento_code = tipo_doc_map.get(venta['tipo_comprobante'], '03') # '03' (Boleta) por defecto
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "InvoiceTypeCode"), listID="0101").text = tipo_documento_code
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "DocumentCurrencyCode")).text = "PEN"

    # 2c. Datos del Emisor (Tu Negocio)
    emisor_ruc = credenciales.get('emisor_ruc')
    # TODO: La razón social también debería estar en la configuración
    emisor_razon_social = "JV STUDIO S.A.C." 
    
    supplier_party = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "AccountingSupplierParty"))
    party_emisor = ET.SubElement(supplier_party, ET.QName(NS_MAP["cac"], "Party"))
    party_identification_emisor = ET.SubElement(party_emisor, ET.QName(NS_MAP["cac"], "PartyIdentification"))
    ET.SubElement(party_identification_emisor, ET.QName(NS_MAP["cbc"], "ID"), schemeID="6").text = emisor_ruc # schemeID 6 es para RUC
    
    party_legal_entity_emisor = ET.SubElement(party_emisor, ET.QName(NS_MAP["cac"], "PartyLegalEntity"))
    ET.SubElement(party_legal_entity_emisor, ET.QName(NS_MAP["cbc"], "RegistrationName")).text = emisor_razon_social
    
    # 2d. Datos del Receptor (Tu Cliente)
    tipo_doc_cliente_map = { 'DNI': '1', 'RUC': '6', 'Otro': '0' }
    cliente_doc_tipo = tipo_doc_cliente_map.get(cliente['tipo_documento'], '0')
    cliente_nombre_completo = f"{cliente['razon_social_nombres']} {cliente['apellidos'] or ''}".strip()
    
    customer_party = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "AccountingCustomerParty"))
    party_cliente = ET.SubElement(customer_party, ET.QName(NS_MAP["cac"], "Party"))
    party_identification_cliente = ET.SubElement(party_cliente, ET.QName(NS_MAP["cac"], "PartyIdentification"))
    ET.SubElement(party_identification_cliente, ET.QName(NS_MAP["cbc"], "ID"), schemeID=cliente_doc_tipo).text = cliente['numero_documento']

    party_legal_entity_cliente = ET.SubElement(party_cliente, ET.QName(NS_MAP["cac"], "PartyLegalEntity"))
    ET.SubElement(party_legal_entity_cliente, ET.QName(NS_MAP["cbc"], "RegistrationName")).text = cliente_nombre_completo
    
    # --- FIN PARTE 2 ---
    # --- INICIO PARTE 3: Detalle de Ítems, Totales y Firma ---

    # 3a. Totales Globales del Comprobante
    tax_total = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "TaxTotal"))
    ET.SubElement(tax_total, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{venta['monto_impuestos']:.2f}"
    
    tax_subtotal = ET.SubElement(tax_total, ET.QName(NS_MAP["cac"], "TaxSubtotal"))
    base_imponible = venta['monto_final_venta'] - venta['monto_impuestos']
    ET.SubElement(tax_subtotal, ET.QName(NS_MAP["cbc"], "TaxableAmount"), currencyID="PEN").text = f"{base_imponible:.2f}"
    ET.SubElement(tax_subtotal, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{venta['monto_impuestos']:.2f}"
    tax_category = ET.SubElement(tax_subtotal, ET.QName(NS_MAP["cac"], "TaxCategory"))
    tax_scheme = ET.SubElement(tax_category, ET.QName(NS_MAP["cac"], "TaxScheme"))
    ET.SubElement(tax_scheme, ET.QName(NS_MAP["cbc"], "ID")).text = "1000" # Código para IGV
    ET.SubElement(tax_scheme, ET.QName(NS_MAP["cbc"], "Name")).text = "IGV"
    ET.SubElement(tax_scheme, ET.QName(NS_MAP["cbc"], "TaxTypeCode")).text = "VAT"
    
    legal_monetary_total = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "LegalMonetaryTotal"))
    ET.SubElement(legal_monetary_total, ET.QName(NS_MAP["cbc"], "LineExtensionAmount"), currencyID="PEN").text = f"{base_imponible:.2f}"
    ET.SubElement(legal_monetary_total, ET.QName(NS_MAP["cbc"], "PayableAmount"), currencyID="PEN").text = f"{venta['monto_final_venta']:.2f}"

    # 3b. Detalle de Ítems (Bucle)
    for i, item in enumerate(items, 1):
        line = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "InvoiceLine"))
        ET.SubElement(line, ET.QName(NS_MAP["cbc"], "ID")).text = str(i)
        
        cantidad = int(item['cantidad'])
        ET.SubElement(line, ET.QName(NS_MAP["cbc"], "InvoicedQuantity"), unitCode="NIU").text = str(cantidad) # NIU = Unidad
        
        line_extension_amount = ET.SubElement(line, ET.QName(NS_MAP["cbc"], "LineExtensionAmount"), currencyID="PEN")
        line_extension_amount.text = f"{float(item['subtotal_item_neto']) / 1.18:.2f}" # Subtotal de línea sin IGV

        pricing_reference = ET.SubElement(line, ET.QName(NS_MAP["cac"], "PricingReference"))
        alt_condition_price = ET.SubElement(pricing_reference, ET.QName(NS_MAP["cac"], "AlternativeConditionPrice"))
        ET.SubElement(alt_condition_price, ET.QName(NS_MAP["cbc"], "PriceAmount"), currencyID="PEN").text = f"{float(item['precio_unitario_venta']):.2f}"
        ET.SubElement(alt_condition_price, ET.QName(NS_MAP["cbc"], "PriceTypeCode")).text = "01" # Precio unitario (incluye IGV)

        # Impuestos de la línea (simplificado)
        tax_total_line = ET.SubElement(line, ET.QName(NS_MAP["cac"], "TaxTotal"))
        ET.SubElement(tax_total_line, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{float(item['subtotal_item_neto']) - (float(item['subtotal_item_neto']) / 1.18):.2f}"
        
        item_node = ET.SubElement(line, ET.QName(NS_MAP["cac"], "Item"))
        ET.SubElement(item_node, ET.QName(NS_MAP["cbc"], "Description")).text = item['descripcion_item_venta']
        
        price_node = ET.SubElement(line, ET.QName(NS_MAP["cac"], "Price"))
        ET.SubElement(price_node, ET.QName(NS_MAP["cbc"], "PriceAmount"), currencyID="PEN").text = f"{float(item['precio_unitario_venta']) / 1.18:.2f}" # Precio sin IGV

    # --- 4. Firma Digital ---
    signer = XMLSigner(method=methods.enveloped, signature_algorithm="rsa-sha256", digest_algorithm="sha256")
    
    cert_chain = [public_cert] + additional_certs
    signed_invoice = signer.sign(invoice, key=private_key, cert=cert_chain)
    
    signature_node = signed_invoice.find(".//ds:Signature", namespaces=NS_MAP)
    signature_placeholder = signed_invoice.find(".//ext:ExtensionContent", namespaces=NS_MAP)
    if signature_placeholder is not None and signature_node is not None:
            signature_placeholder.append(signature_node)
    
    # --- 5. Devolver Resultados ---
    xml_string = ET.tostring(signed_invoice, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    nombre_base = f"{emisor_ruc}-{tipo_documento_code}-{venta['serie_comprobante']}-{venta['numero_comprobante']}"
    
    return xml_string, nombre_base


@main_bp.route('/ventas/xml/<int:venta_id>')
@login_required
@admin_required
def generar_xml_venta(venta_id):
    """
    Llama a la función interna para generar el XML firmado y lo devuelve como descarga.
    """
    try:
        xml_firmado_str, nombre_base = _generar_y_firmar_xml(venta_id)
        nombre_archivo = f"{nombre_base}.xml"
        return Response(xml_firmado_str, mimetype="application/xml", headers={"Content-Disposition": f"attachment;filename={nombre_archivo}"})
    except Exception as e:
        flash(f"Error al generar el archivo XML: {e}", "danger")
        current_app.logger.error(f"Error en generar_xml_venta: {e}")
        return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

@main_bp.route('/ventas/enviar-sunat/<int:venta_id>', methods=['POST'])
@login_required
@admin_required
def enviar_sunat(venta_id):
    """
    Genera, empaqueta y envía el comprobante al servicio de homologación (pruebas) de la SUNAT.
    """
    # URL del Servicio de Homologación (Beta) de SUNAT
    SUNAT_WSDL_URL = 'https://e-beta.sunat.gob.pe/ol-ti-itcpfegem-beta/billService?wsdl'
    
    try:
        # 1. Generar el XML firmado y el nombre del archivo
        xml_firmado_str, nombre_base = _generar_y_firmar_xml(venta_id)
        nombre_archivo_zip = f"{nombre_base}.zip"

        # 2. Comprimir el XML y codificar en Base64
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{nombre_base}.xml", xml_firmado_str)
        zip_data = zip_buffer.getvalue()
        zip_base64 = base64.b64encode(zip_data).decode('utf-8')
        
        # 3. Cargar credenciales SOL
        instance_path = current_app.instance_path
        credentials_file_path = os.path.join(instance_path, 'sunat_credentials.json')
        if not os.path.exists(credentials_file_path):
            raise ValueError("No se han configurado las credenciales SOL.")
        with open(credentials_file_path, 'r') as f:
            credenciales = json.load(f)

        usuario_sol = credenciales.get('usuario_sol')
        clave_sol = credenciales.get('clave_sol')
        if not usuario_sol or not clave_sol:
            raise ValueError("Usuario o Clave SOL no están configurados.")

        # 4. Conexión y Envío a SUNAT usando 'zeep'
        transport = Transport(timeout=20)
        client = Client(wsdl=SUNAT_WSDL_URL, transport=transport, wsse=UsernameToken(usuario_sol, clave_sol))
        
        # Llamar al método 'sendBill' del servicio web
        response = client.service.sendBill(fileName=nombre_archivo_zip, contentFile=zip_base64)
        
        # 5. Procesar la Respuesta (CDR)
        if response and hasattr(response, 'applicationResponse'):
            cdr_zip_base64 = response.applicationResponse
            cdr_zip_data = base64.b64decode(cdr_zip_base64)
            
            cdr_zip_buffer = io.BytesIO(cdr_zip_data)
            with zipfile.ZipFile(cdr_zip_buffer, 'r') as zip_ref:
                nombre_cdr = zip_ref.namelist()[0]
                with zip_ref.open(nombre_cdr) as cdr_xml_file:
                    cdr_tree = ET.parse(cdr_xml_file)
                    
                    ns = {'ar': "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2",
                          'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"}
                    
                    response_code = cdr_tree.find('.//cbc:ResponseCode', namespaces=ns).text
                    response_desc = cdr_tree.find('.//cbc:Description', namespaces=ns).text
                    
                    if response_code == "0":
                        estado_sunat = "Aceptada"
                        flash(f"¡ÉXITO! Comprobante {nombre_base} ACEPTADO por SUNAT.", 'success')
                        flash(f"Respuesta SUNAT: {response_desc}", 'info')
                    else:
                        estado_sunat = f"Rechazada ({response_code})"
                        flash(f"Comprobante {nombre_base} RECHAZADO por SUNAT.", 'danger')
                        flash(f"Motivo: {response_desc}", 'warning')
                    
                    # Actualizar el estado en nuestra base de datos
                    db = get_db()
                    with db.cursor() as cursor:
                        cursor.execute("UPDATE ventas SET estado_sunat = %s WHERE id = %s", (estado_sunat, venta_id))
                        db.commit()
        else:
            raise ValueError("La SUNAT no devolvió una respuesta válida (CDR).")

    except Fault as fault:
        flash(f"Error de SOAP al comunicarse con SUNAT: {fault.message}", "danger")
    except Exception as e:
        flash(f"Error al enviar a SUNAT: {e}", "danger")

    return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))
    
    
@main_bp.route('/configuracion/estilos')
@login_required
@admin_required
def listar_estilos():
    """
    Muestra la lista de todos los estilos (cortes, peinados, etc.).
    """
    try:
        db = get_db()
        with db.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT * FROM estilos ORDER BY nombre")
            estilos = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Error al acceder a los estilos: {err}", "danger")
        estilos = []
        
    return render_template('estilos/lista_estilos.html', 
                           estilos=estilos,
                           titulo_pagina="Catálogo de Estilos y Cortes")

@main_bp.route('/configuracion/estilos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_estilo():
    """
    Maneja la creación de un nuevo estilo, incluyendo la subida de la foto.
    """
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        descripcion = request.form.get('descripcion')
        foto = request.files.get('foto')
        activo = 'activo' in request.form

        if not nombre:
            flash('El nombre del estilo es obligatorio.', 'warning')
            return redirect(url_for('main.nuevo_estilo'))

        foto_path = None
        if foto and foto.filename != '':
            # Guardar la foto de forma segura
            filename = secure_filename(foto.filename)
            # Crear una subcarpeta para las fotos de estilos
            upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'estilos')
            os.makedirs(upload_folder, exist_ok=True)
            foto_path = os.path.join(upload_folder, filename)
            foto.save(foto_path)
            # Guardamos la ruta relativa para usarla en el HTML
            foto_path_db = f'uploads/estilos/{filename}'
        else:
            foto_path_db = None

        try:
            db = get_db()
            with db.cursor() as cursor:
                sql = "INSERT INTO estilos (nombre, descripcion, foto_path, activo) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (nombre, descripcion, foto_path_db, activo))
                db.commit()
            flash(f'Estilo "{nombre}" creado exitosamente.', 'success')
            return redirect(url_for('main.listar_estilos'))
        except mysql.connector.Error as err:
            db.rollback()
            flash(f'Error al crear el estilo: {err}', 'danger')
        
        return redirect(url_for('main.nuevo_estilo'))

    return render_template('estilos/form_estilo.html', 
                           es_nueva=True,
                           titulo_form="Crear Nuevo Estilo",
                           action_url=url_for('main.nuevo_estilo'))
    
    
@main_bp.route('/configuracion/estilos/editar/<int:estilo_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_estilo(estilo_id):
    """
    Maneja la edición de un estilo existente, incluyendo la actualización de la foto.
    """
    db_conn = get_db()
    
    # Obtener el estilo actual para mostrar sus datos en el formulario
    with db_conn.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT * FROM estilos WHERE id = %s", (estilo_id,))
        estilo_actual = cursor.fetchone()
    
    if not estilo_actual:
        flash("Estilo no encontrado.", "warning")
        return redirect(url_for('main.listar_estilos'))

    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            foto = request.files.get('foto')
            activo = 'activo' in request.form

            if not nombre:
                raise ValueError("El nombre del estilo es obligatorio.")

            foto_path_db = estilo_actual.get('foto_path') # Mantener la foto actual por defecto
            
            # Si se sube una nueva foto, se procesa y reemplaza la anterior
            if foto and foto.filename != '':
                filename = secure_filename(foto.filename)
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads', 'estilos')
                os.makedirs(upload_folder, exist_ok=True)
                
                # Opcional: Borrar la foto antigua si existe
                if foto_path_db:
                    ruta_foto_antigua = os.path.join(current_app.root_path, 'static', foto_path_db)
                    if os.path.exists(ruta_foto_antigua):
                        os.remove(ruta_foto_antigua)

                ruta_guardado_nueva = os.path.join(upload_folder, filename)
                foto.save(ruta_guardado_nueva)
                foto_path_db = f'uploads/estilos/{filename}'

            with db_conn.cursor() as cursor:
                sql = "UPDATE estilos SET nombre=%s, descripcion=%s, foto_path=%s, activo=%s WHERE id=%s"
                val = (nombre, descripcion, foto_path_db, activo, estilo_id)
                cursor.execute(sql, val)
                db_conn.commit()
            
            flash(f'Estilo "{nombre}" actualizado exitosamente.', 'success')
            return redirect(url_for('main.listar_estilos'))

        except (ValueError, mysql.connector.Error, Exception) as e:
            db_conn.rollback()
            flash(f"Error al actualizar el estilo: {e}", "danger")
        
        return redirect(url_for('main.editar_estilo', estilo_id=estilo_id))

    # Método GET: Muestra el formulario con los datos actuales
    return render_template('estilos/form_estilo.html', 
                           es_nueva=False,
                           titulo_form=f"Editar Estilo: {estilo_actual['nombre']}",
                           action_url=url_for('main.editar_estilo', estilo_id=estilo_id),
                           estilo=estilo_actual) # Pasar el objeto 'estilo' a la plantilla    
    
    
@main_bp.route('/clientes/detalle/<int:cliente_id>')
@login_required
def detalle_cliente(cliente_id):
    """
    Muestra la página de detalle de un cliente, incluyendo su historial de visitas.
    """
    db_conn = get_db()
    
    try:
        with db_conn.cursor(dictionary=True) as cursor:
            # 1. Obtener los datos principales del cliente
            cursor.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
            cliente = cursor.fetchone()
            if not cliente:
                flash("Cliente no encontrado.", "warning")
                return redirect(url_for('main.listar_clientes'))

            # 2. Obtener su historial de ventas (visitas)
            sql_ventas = """
                SELECT 
                    v.id, v.fecha_venta, v.monto_final_venta,
                    e.nombre_display AS colaborador_nombre
                FROM ventas v
                JOIN empleados e ON v.empleado_id = e.id
                WHERE v.cliente_receptor_id = %s OR v.cliente_facturacion_id = %s
                ORDER BY v.fecha_venta DESC
            """
            cursor.execute(sql_ventas, (cliente_id, cliente_id))
            historial_ventas = cursor.fetchall()
            
            # 3. Obtener sus membresías activas o pasadas
            cursor.execute("""
                SELECT mp.nombre, cm.fecha_inicio, cm.fecha_fin, cm.estado
                FROM cliente_membresias cm
                JOIN membresia_planes mp ON cm.plan_id = mp.id
                WHERE cm.cliente_id = %s
                ORDER BY cm.fecha_inicio DESC
            """, (cliente_id,))
            historial_membresias = cursor.fetchall()
            
    except mysql.connector.Error as err:
        flash(f"Error al cargar el historial del cliente: {err}", "danger")
        return redirect(url_for('main.listar_clientes'))

    return render_template('clientes/detalle_cliente.html',
                           cliente=cliente,
                           historial_ventas=historial_ventas,
                           historial_membresias=historial_membresias,
                           titulo_pagina=f"Detalle de Cliente")



