# -------------------------------------------------------------------------
# 1. IMPORTACIONES ESTÁNDAR Y DE TERCEROS
# -------------------------------------------------------------------------
import os
import io
import json
import math
import zipfile
import base64
import calendar
from datetime import datetime, date, time, timedelta, timezone
from urllib.parse import quote, quote_plus
import requests 
import pytz
from app.services.whatsapp_service import enviar_alerta_reserva
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


# Librerías de Flask
# (Agregamos 'send_file' que faltaba para la descarga del CDR)
from flask import (
    Blueprint, render_template, current_app, g, request, session, 
    redirect, url_for, flash, jsonify, Response, send_file
)

# Librerías de Base de Datos
import psycopg2
import psycopg2.extras

# Librerías de Autenticación y Seguridad
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_login import login_user, logout_user, login_required, current_user

# Librerías de Datos y Archivos
import pandas as pd

# Librerías para Facturación Electrónica (XML, Firma, SOAP)
from lxml import etree as ET
from signxml import XMLSigner, methods
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import serialization
from zeep import Client, Transport
from zeep.exceptions import Fault
from zeep.wsse.username import UsernameToken

# -------------------------------------------------------------------------
# 2. IMPORTACIONES LOCALES (De tu propio proyecto)
# -------------------------------------------------------------------------
from .db import get_db
from .models import User
from .decorators import admin_required

# -------------------------------------------------------------------------
# 3. DEFINICIÓN DEL BLUEPRINT (El corazón de las rutas)
# -------------------------------------------------------------------------
main_bp = Blueprint('main', __name__)

# --- Funciones Auxiliares para la Base de Datos ---



def timedelta_to_hhmm_str(td):
    """Convierte un timedelta a un string en formato HH:MM:SS."""
    if td is None: 
        return "00:00:00"
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def timedelta_to_time_obj(td):
    """
    Convierte un objeto timedelta (duración) a un objeto time (hora del reloj).
    Necesario para comparar horarios de turnos.
    """
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


@main_bp.route('/ayuda/contenido')
@login_required
def obtener_ayuda_contenido():
    path = request.args.get('path', '')
    
    # Lógica de mapeo simple (URL -> Template)
    template_name = 'manuales/general.html'
    
    if 'finanzas' in path:
        template_name = 'manuales/finanzas.html'
    elif 'reservas' in path or 'agenda' in path:
        template_name = 'manuales/reservas.html'
    elif 'ventas' in path or 'caja' in path or 'comanda' in path:
        template_name = 'manuales/ventas.html'
    elif 'inventario' in path or 'productos' in path or 'compras' in path:
        template_name = 'manuales/inventario.html'
    elif 'clientes' in path:
        template_name = 'manuales/clientes.html'
        
    try:
        return render_template(template_name)
    except Exception as e:
        return f"<div class='alert alert-danger'>Error cargando ayuda: {str(e)}</div>"

@main_bp.route('/')
@login_required
def index():
    """
    Muestra el dashboard principal con KPIs y alertas de cumpleaños.
    """
    db_conn = get_db()
    hoy = date.today()
    
    # --- 1. INICIALIZAR VARIABLES CON VALORES POR DEFECTO ---
    # Esto asegura que si la BD falla, el dashboard cargue vacío pero sin errores
    ventas_hoy = {'numero_ventas': 0, 'total_servicios': 0.00, 'total_productos': 0.00}
    datos_para_plantilla = {
        'citas_hoy': {'numero_citas': 0},
        'productos_stock_bajo': [],
        'membresias_por_vencer': [],
        'proximas_citas': [],
        'clientes_cumpleanos_hoy': [],
        'clientes_cumpleanos_proximos': [],
        'fecha_alerta_hoy': hoy,
        'fecha_alerta_proxima': hoy + timedelta(days=2)
    }

    try:
        # Lógica para Administradores
        # Ajusta 'Administrador' si tu rol se llama diferente en la BD
        if getattr(current_user, 'rol', '') == 'Administrador' or getattr(current_user, 'rol_nombre', '') == 'Administrador':
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # 1. Ventas del día (Postgres: COALESCE)
                cursor.execute("""
                    SELECT 
                        COUNT(id) as numero_ventas,
                        COALESCE(SUM(subtotal_servicios), 0) as total_servicios,
                        COALESCE(SUM(subtotal_productos), 0) as total_productos
                    FROM ventas 
                    WHERE DATE(fecha_venta) = %s AND estado_pago != 'Anulado'
                """, (hoy,))
                resultado_ventas = cursor.fetchone()
                if resultado_ventas:
                    ventas_hoy = resultado_ventas

                # 2. Citas del día
                cursor.execute("SELECT COUNT(id) as numero_citas FROM reservas WHERE DATE(fecha_hora_inicio) = %s AND estado NOT IN ('Cancelada', 'No Asistio')", (hoy,))
                datos_para_plantilla['citas_hoy'] = cursor.fetchone()

                # 3. Productos con stock bajo
                cursor.execute("SELECT id, nombre, stock_actual, stock_minimo FROM productos WHERE activo = TRUE AND stock_actual <= stock_minimo ORDER BY stock_actual ASC")
                datos_para_plantilla['productos_stock_bajo'] = cursor.fetchall()
                
                # 4. Membresías por vencer
                fecha_limite_vencimiento = hoy + timedelta(days=7)
                sql_membresias = """
                    SELECT c.razon_social_nombres, c.apellidos, c.telefono, cm.fecha_fin, mp.nombre as plan_nombre
                    FROM cliente_membresias cm
                    JOIN clientes c ON cm.cliente_id = c.id
                    JOIN membresia_planes mp ON cm.plan_id = mp.id
                    WHERE cm.estado = 'Activa' AND cm.fecha_fin BETWEEN %s AND %s
                    ORDER BY cm.fecha_fin ASC
                """
                cursor.execute(sql_membresias, (hoy, fecha_limite_vencimiento))
                datos_para_plantilla['membresias_por_vencer'] = cursor.fetchall()
                              
        # Lógica para Colaboradores
        else:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Postgres: COALESCE en lugar de IFNULL
                sql = """
                    SELECT r.id, r.fecha_hora_inicio, s.nombre as servicio_nombre,
                           CONCAT(c.razon_social_nombres, ' ', COALESCE(c.apellidos, '')) AS cliente_nombre
                    FROM reservas r 
                    JOIN servicios s ON r.servicio_id = s.id 
                    LEFT JOIN clientes c ON r.cliente_id = c.id
                    WHERE r.empleado_id = %s AND DATE(r.fecha_hora_inicio) = %s 
                      AND r.estado = 'Programada' AND r.fecha_hora_inicio >= CURRENT_TIMESTAMP
                    ORDER BY r.fecha_hora_inicio ASC LIMIT 5
                """
                cursor.execute(sql, (current_user.id, hoy))
                datos_para_plantilla['proximas_citas'] = cursor.fetchall()

        # --- LÓGICA DE CUMPLEAÑOS (General) ---
        anio_actual = hoy.year
        fecha_proxima = hoy + timedelta(days=2)
        
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Cumpleaños de HOY (Postgres: EXTRACT)
            sql_hoy = """
                SELECT c.id, c.razon_social_nombres, c.apellidos, c.telefono 
                FROM clientes c 
                LEFT JOIN cliente_comunicaciones cc 
                    ON c.id = cc.cliente_id AND cc.tipo_comunicacion = 'SALUDO_CUMPLEANOS' AND cc.año_aplicable = %s 
                WHERE EXTRACT(MONTH FROM c.fecha_nacimiento) = %s 
                  AND EXTRACT(DAY FROM c.fecha_nacimiento) = %s 
                  AND cc.id IS NULL
            """
            cursor.execute(sql_hoy, (anio_actual, hoy.month, hoy.day))
            datos_para_plantilla['clientes_cumpleanos_hoy'] = cursor.fetchall()
            
            # Próximos cumpleaños
            sql_proximos = """
                SELECT c.id, c.razon_social_nombres, c.apellidos, c.telefono 
                FROM clientes c 
                LEFT JOIN cliente_comunicaciones cc 
                    ON c.id = cc.cliente_id AND cc.tipo_comunicacion = 'INVITACION_CUMPLEANOS' AND cc.año_aplicable = %s 
                WHERE EXTRACT(MONTH FROM c.fecha_nacimiento) = %s 
                  AND EXTRACT(DAY FROM c.fecha_nacimiento) = %s 
                  AND cc.id IS NULL
            """
            cursor.execute(sql_proximos, (anio_actual, fecha_proxima.month, fecha_proxima.day))
            datos_para_plantilla['clientes_cumpleanos_proximos'] = cursor.fetchall()

    except Exception as e:
        print(f"Error en Dashboard: {e}")
        # No retornamos aquí, dejamos que el flujo continúe hacia el return final

    # --- 2. RETORNO SEGURO ---
    # Este return está FUERA del try/except, garantizando que siempre se ejecute
    return render_template('index.html', 
                           ventas_hoy=ventas_hoy, 
                           **datos_para_plantilla)    

# --- RUTAS DE AUTENTICACIÓN ---

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Si ya está autenticado y tiene una sucursal, va al index.
        if 'sucursal_id' in session:
            return redirect(url_for('main.index'))
        # Si está autenticado pero sin sucursal, va a la selección.
        else:
            return redirect(url_for('main.seleccionar_sucursal'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        remember = 'remember' in request.form
        
        db_conn = get_db()
        try:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # 1. Obtener datos del usuario y su rol
                cursor.execute("""
                    SELECT e.*, r.nombre as rol_nombre
                    FROM empleados e
                    LEFT JOIN roles r ON e.rol_id = r.id
                    WHERE e.email = %s AND e.activo = TRUE
                """, (email,))
                user_data = cursor.fetchone()
                
                # 2. Validar contraseña
                if user_data and check_password_hash(user_data['password'], password):
                    user = User(
                        id=user_data['id'], 
                        nombres=user_data['nombres'],
                        apellidos=user_data['apellidos'],
                        email=user_data['email'],
                        rol_id=user_data['rol_id'],
                        rol_nombre=user_data['rol_nombre']
                        # No guardamos sucursal_id por defecto aquí
                    )
                    
                    # 3. Consultar sucursales asignadas y ACTIVAS
                    cursor.execute("""
                        SELECT s.id, s.nombre 
                        FROM sucursales s
                        JOIN empleado_sucursales es ON s.id = es.sucursal_id
                        WHERE es.empleado_id = %s AND s.activo = TRUE
                    """, (user.id,))
                    sucursales_asignadas = cursor.fetchall()
                    
                    # --- LÓGICA DE REDIRECCIÓN ---
                    # Caso 0: Sin sucursales asignadas o activas
                    if not sucursales_asignadas:
                        flash("Credenciales correctas, pero no tiene acceso a ninguna sucursal activa. Contacte al administrador.", "warning")
                        return render_template('login.html')

                    # Caso 1: Una única sucursal asignada
                    if len(sucursales_asignadas) == 1:
                        sucursal = sucursales_asignadas[0]
                        session['sucursal_id'] = sucursal['id']
                        session['sucursal_nombre'] = sucursal['nombre']
                        login_user(user, remember=remember)
                        flash(f"Acceso automático a su única sucursal: {sucursal['nombre']}.", "info")
                        return redirect(url_for('main.index'))
                    
                    # Caso 2: Múltiples sucursales
                    else:
                        login_user(user, remember=remember)
                        # No guardamos sucursal en sesión, forzamos la selección
                        return redirect(url_for('main.seleccionar_sucursal'))
                        
                else:
                    flash('Correo o contraseña incorrectos, o el usuario está inactivo.', 'danger')
                    
        except Exception as e:
            flash(f"Error de sistema durante el inicio de sesión: {e}", "danger")
            current_app.logger.error(f"Login error: {e}")

    return render_template('login.html')


@main_bp.route('/auth/seleccionar-sucursal', methods=['GET', 'POST'])
@login_required
def seleccionar_sucursal():
    """
    Permite al usuario con múltiples sucursales seleccionar con cuál desea trabajar.
    Esta página es obligatoria si el usuario no tiene una sucursal en la sesión.
    """
    db_conn = get_db()
    
    # Obtener siempre las sucursales permitidas para el usuario desde la BD.
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Si el usuario es Administrador, puede elegir cualquier sucursal activa
            if hasattr(current_user, 'rol_nombre') and current_user.rol_nombre == 'Administrador':
                 cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            else:
                # Si no, solo las que tiene asignadas
                cursor.execute("""
                    SELECT s.id, s.nombre FROM sucursales s 
                    JOIN empleado_sucursales es ON s.id = es.sucursal_id 
                    WHERE es.empleado_id = %s AND s.activo = TRUE
                """, (current_user.id,))
            
            sucursales_permitidas = cursor.fetchall()

    except Exception as e:
        flash(f"Error de base de datos al buscar sus sucursales: {e}", "danger")
        return redirect(url_for('main.logout')) # Forzar logout si hay error grave

    # Si por alguna razón (ej. le quitaron permisos) ya no tiene sucursales, se cierra sesión.
    if not sucursales_permitidas:
        logout_user()
        session.clear()
        flash("No tiene acceso a ninguna sucursal activa. Contacte al administrador.", "danger")
        return redirect(url_for('main.login'))

    # Si solo tiene una sucursal, se la asignamos y lo mandamos al dashboard.
    if len(sucursales_permitidas) == 1:
        session['sucursal_id'] = sucursales_permitidas[0]['id']
        session['sucursal_nombre'] = sucursales_permitidas[0]['nombre']
        return redirect(url_for('main.index'))

    # Si se envía el formulario (POST)
    if request.method == 'POST':
        sucursal_id_seleccionada = request.form.get('sucursal_id', type=int)
        
        # Validar que la sucursal seleccionada esté en la lista permitida.
        sucursal_valida = next((s for s in sucursales_permitidas if s['id'] == sucursal_id_seleccionada), None)

        if sucursal_valida:
            session['sucursal_id'] = sucursal_valida['id']
            session['sucursal_nombre'] = sucursal_valida['nombre']
            flash(f"Ha ingresado a la sucursal '{sucursal_valida['nombre']}'.", "success")
            return redirect(url_for('main.index'))
        else:
            flash("Selección de sucursal inválida o no permitida.", "danger")
            # Vuelve a mostrar la página de selección
            return redirect(url_for('main.seleccionar_sucursal'))

    # Método GET: Muestra la página de selección.
    return render_template('auth/seleccionar_sucursal.html', sucursales=sucursales_permitidas)


@main_bp.route('/cambiar-sucursal/<int:sucursal_id>')
@login_required
def cambiar_sucursal_activa(sucursal_id):
    """
    Permite cambiar la sucursal activa en la sesión sin cerrar sesión.
    """
    db = get_db()
    # Verificar si el usuario tiene permiso real para esa sucursal
    with db.cursor() as cursor:
        cursor.execute("SELECT 1 FROM empleado_sucursales WHERE empleado_id=%s AND sucursal_id=%s", (current_user.id, sucursal_id))
        if cursor.fetchone():
            session['sucursal_id'] = sucursal_id
            
            # Actualizar nombre en sesión también
            cursor.execute("SELECT nombre FROM sucursales WHERE id=%s", (sucursal_id,))
            row = cursor.fetchone()
            session['sucursal_nombre'] = row[0] if row else "Sucursal"
            
            flash(f"Cambiado a: {session['sucursal_nombre']}", "success")
        else:
            flash("No tienes acceso a esta sucursal.", "danger")
            
    return redirect(request.referrer or url_for('main.index'))



@main_bp.route('/logout')
@login_required # Solo un usuario logueado puede acceder a esta ruta para desloguearse
def logout():
    """
    Maneja el cierre de sesión del usuario.
    """
    logout_user()
    flash('Has cerrado sesión exitosamente.', 'success')
    return redirect(url_for('main.login'))

# --- RUTAS PARA LA GESTIÓN DE CLIENTES ---
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
            # Usamos INSERT ... ON CONFLICT DO NOTHING para evitar un error si se hace clic dos veces rápidamente.
            # La constraint UNIQUE en la tabla ya previene duplicados.
            sql = """
                INSERT INTO cliente_comunicaciones 
                    (cliente_id, tipo_comunicacion, año_aplicable, registrado_por_colaborador_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """
            cursor.execute(sql, (cliente_id, tipo_comunicacion, anio_aplicable, current_user.id))
            db.commit()

        return jsonify({"success": True, "message": "Comunicación registrada exitosamente."})

    except Exception as err:
        db.rollback()
        current_app.logger.error(f"Error DB en api_registrar_comunicacion: {err}")
        return jsonify({"success": False, "message": f"Error de base de datos: {err}"}), 500


@main_bp.route('/clientes', methods=['GET'])
@login_required
def listar_clientes():
    db_conn = get_db()
    cursor = None
    try:
        # Obtener término de búsqueda (si existe)
        q = request.args.get('q', '').strip()
        
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            if q:
                # BÚSQUEDA FILTRADA (ILIKE es clave para ignorar mayúsculas)
                sql = """
                    SELECT id, razon_social_nombres, apellidos, tipo_documento, 
                           numero_documento, telefono, puntos_fidelidad 
                    FROM clientes 
                    WHERE 
                        razon_social_nombres ILIKE %s OR 
                        apellidos ILIKE %s OR 
                        numero_documento ILIKE %s OR
                        telefono ILIKE %s
                    ORDER BY razon_social_nombres ASC
                """
                termino = f"%{q}%"
                cursor.execute(sql, (termino, termino, termino, termino))
            else:
                # LISTADO COMPLETO (Limitado a 50 para no saturar si hay muchos)
                sql = """
                    SELECT id, razon_social_nombres, apellidos, tipo_documento, 
                           numero_documento, telefono, puntos_fidelidad 
                    FROM clientes 
                    ORDER BY razon_social_nombres ASC 
                    LIMIT 50
                """
                cursor.execute(sql)
            
            clientes = cursor.fetchall()

        return render_template('clientes/lista_clientes.html', 
                               clientes=clientes, 
                               termino_busqueda=q)

    except Exception as e:
        # current_app.logger.error(f"Error listando clientes: {e}")
        flash(f"Error al cargar clientes: {e}", "danger")
        return redirect(url_for('main.index'))

# -------------------------------------------------------------------------
# GESTIÓN DE CLIENTES
# -------------------------------------------------------------------------
@main_bp.route('/clientes/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    db_conn = get_db()
    
    # Cargar lista de clientes para el buscador de Apoderados (Solo Titulares)
    # Traemos ID, Nombre y Telefono para ayudar a buscar
    posibles_apoderados = []
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, razon_social_nombres, apellidos, telefono FROM clientes WHERE apoderado_id IS NULL ORDER BY razon_social_nombres")
        posibles_apoderados = cur.fetchall()

    if request.method == 'POST':
        # Datos básicos
        tipo_documento = request.form.get('tipo_documento')
        numero_documento = request.form.get('numero_documento', '').strip() or None
        nombres = request.form.get('razon_social_nombres', '').strip().title()
        
        # Nuevos campos de apellidos
        apellido_paterno = request.form.get('apellido_paterno', '').strip().title() or None
        apellido_materno = request.form.get('apellido_materno', '').strip().title() or None
        
        # Construir apellidos concatenados para mantener compatibilidad
        parts = []
        if apellido_paterno: parts.append(apellido_paterno)
        if apellido_materno: parts.append(apellido_materno)
        apellidos = " ".join(parts) if parts else None
        direccion = request.form.get('direccion', '').strip() or None
        email = request.form.get('email', '').strip() or None
        telefono = request.form.get('telefono', '').strip() or None
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        puntos = request.form.get('puntos_fidelidad', 0, type=int)
        
        # Campos nuevos
        genero = request.form.get('genero', 'Masculino').strip()
        preferencia_servicio = request.form.get('preferencia_servicio', 'Barberia').strip()

        # NUEVO: Apoderado ID
        apoderado_id = request.form.get('apoderado_id')
        if not apoderado_id or apoderado_id == '':
            apoderado_id = None # Es Cliente Regular
        
        errores = []
        if not nombres: errores.append("El nombre es obligatorio.")
        
        # Lógica de Teléfono:
        # Si NO tiene apoderado (es Regular), el teléfono es OBLIGATORIO.
        # Si TIENE apoderado (es Dependiente), el teléfono es OPCIONAL.
        if not apoderado_id and not telefono:
            errores.append("El teléfono es obligatorio para clientes titulares.")

        # Validar fecha
        fecha_nacimiento = None
        if fecha_nacimiento_str:
            try:
                fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()
            except ValueError:
                errores.append("Fecha inválida.")

        # Validar duplicados (Solo si se ingresó teléfono)
        if telefono:
            cursor_check = None
            try:
                cursor_check = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Permitimos mismo teléfono SOLO si tienen diferente nombre (tu lógica anterior)
                cursor_check.execute("SELECT id FROM clientes WHERE telefono = %s AND LOWER(razon_social_nombres) = LOWER(%s)", (telefono, nombres))
                if cursor_check.fetchone():
                    errores.append(f"Ya existe un cliente con este nombre y teléfono.")
            finally:
                if cursor_check: cursor_check.close()

        if errores:
            for err in errores: flash(err, 'warning')
            return render_template('clientes/form_cliente.html', 
                                   es_nueva=True, 
                                   titulo_form="Registrar Nuevo Cliente",
                                   action_url=url_for('main.nuevo_cliente'),
                                   posibles_apoderados=posibles_apoderados, # Pasamos la lista
                                   form_data=request.form)

        # Insertar
        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            sql = """INSERT INTO clientes 
                        (tipo_documento, numero_documento, razon_social_nombres, apellidos, 
                         apellido_paterno, apellido_materno,
                         direccion, email, telefono, fecha_nacimiento, puntos_fidelidad, apoderado_id, genero, preferencia_servicio) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            
            cursor_insert.execute(sql, (tipo_documento, numero_documento, nombres, apellidos, 
                                        apellido_paterno, apellido_materno,
                                        direccion, email, telefono, fecha_nacimiento, puntos, apoderado_id, genero, preferencia_servicio))
            db_conn.commit()
            
            # --- LÓGICA DE MARKETING POST-REGISTRO ---
            flash_message = 'Cliente registrado exitosamente.'
            if telefono:
                try:
                    # 1. Limpiar y formatear teléfono
                    telefono_limpio = ''.join(filter(str.isdigit, telefono))
                    if len(telefono_limpio) == 9:
                        telefono_limpio = '51' + telefono_limpio
                    
                    # 2. Construir mensaje
                    nombre_cliente = nombres.split(' ')[0] # Usar solo el primer nombre
                    link_redes = "https://www.instagram.com/stories/jvstudio_formen/"
                    link_app = "https://acortar.link/nghOjU" # O la URL que corresponda
                    
                    mensaje = f'Hola {nombre_cliente}! 👋 Bienvenido a la familia JV Studio. 💈💇‍♂️ Gracias por tu preferencia. Síguenos en redes para ver nuestros trabajos: {link_redes} y reserva tu próxima cita fácil aquí: {link_app}'
                    
                    # 3. Codificar y generar enlace
                    mensaje_codificado = quote(mensaje)
                    link_whatsapp = f"https://wa.me/{telefono_limpio}?text={mensaje_codificado}"
                    
                    # 4. Construir flash con HTML
                    flash_message = (
                        'Cliente registrado exitosamente. '
                        f'<a href="{link_whatsapp}" target="_blank" class="btn btn-success btn-sm ms-2">'
                        '<i class="fab fa-whatsapp"></i> Enviar Bienvenida'
                        '</a>'
                    )
                except Exception as e:
                    current_app.logger.error(f"Error al generar link de WhatsApp para {nombres}: {e}")
                    # Si falla, el mensaje flash simple aún se mostrará
            
            flash(flash_message, 'success')
            return redirect(url_for('main.listar_clientes'))

        except Exception as e:
            db_conn.rollback()
            flash(f"Error al registrar: {e}", "danger")
            return render_template('clientes/form_cliente.html', 
                                   es_nueva=True, 
                                   titulo_form="Registrar Nuevo Cliente",
                                   action_url=url_for('main.nuevo_cliente'),
                                   posibles_apoderados=posibles_apoderados,
                                   form_data=request.form)
        finally:
            if cursor_insert: cursor_insert.close()
    
    return render_template('clientes/form_cliente.html', 
                           es_nueva=True, 
                           titulo_form="Registrar Nuevo Cliente",
                           action_url=url_for('main.nuevo_cliente'),
                           posibles_apoderados=posibles_apoderados)

@main_bp.route('/api/clientes/crear', methods=['POST'])
@login_required
def api_crear_cliente_rapido():
    """
    API para crear un cliente rápidamente desde el modal de reservas.
    """
    data = request.get_json()
    nombre = data.get('razon_social_nombres', '').strip().title()
    apellido_paterno = data.get('apellido_paterno', '').strip().title() or None
    apellido_materno = data.get('apellido_materno', '').strip().title() or None
    telefono = data.get('telefono', '').strip()
    documento = data.get('numero_documento', '').strip() or None

    parts = []
    if apellido_paterno: parts.append(apellido_paterno)
    if apellido_materno: parts.append(apellido_materno)
    apellidos = " ".join(parts) if parts else None

    # Si hay apellidos, el nombre de visualización podría incluir el apellido para mayor claridad
    # Pero el select2 muestra "{razon_social_nombres} ({telefono})"
    # Quizás queramos actualizar lo que devuelve la API también.

    if not nombre or not telefono:
        return jsonify({'success': False, 'message': 'Nombre y Teléfono son obligatorios.'}), 400

    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Verificar duplicados por teléfono
        cursor.execute("SELECT id FROM clientes WHERE telefono = %s", (telefono,))
        if cursor.fetchone():
            return jsonify({'success': False, 'message': 'Ya existe un cliente con ese teléfono.'}), 400

        # 2. Insertar
        sql = """
            INSERT INTO clientes (razon_social_nombres, apellidos, apellido_paterno, apellido_materno, telefono, numero_documento, fecha_registro)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE)
            RETURNING id, razon_social_nombres, apellidos
        """
        cursor.execute(sql, (nombre, apellidos, apellido_paterno, apellido_materno, telefono, documento))
        nuevo_cliente = cursor.fetchone()
        db.commit()
        cursor.close()

        # Construir texto para el select2
        display_text = f"{nuevo_cliente['razon_social_nombres']}"
        if nuevo_cliente['apellidos']:
            display_text += f" {nuevo_cliente['apellidos']}"
        display_text += f" ({telefono})"

        return jsonify({
            'success': True, 
            'cliente': {
                'id': nuevo_cliente['id'],
                'text': display_text
            }
        })

    except Exception as e:
        if db: db.rollback()
        current_app.logger.error(f"Error api_crear_cliente_rapido: {e}")
        return jsonify({'success': False, 'message': f'Error interno: {str(e)}'}), 500


@main_bp.route('/clientes/ver/<int:cliente_id>')
@login_required
def ver_cliente(cliente_id):
    try:
        db = get_db()
        # Usar RealDictCursor para pasar el objeto directo a la plantilla
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
            cliente_encontrado = cursor.fetchone()
        
        if not cliente_encontrado:
            flash(f'Cliente no encontrado.', 'warning')
            return redirect(url_for('main.listar_clientes'))
            
    except Exception as err:
        flash(f"Error al ver cliente: {err}", "danger")
        return redirect(url_for('main.listar_clientes'))

    return render_template('clientes/ver_cliente.html', cliente=cliente_encontrado)


@main_bp.route('/clientes/editar/<int:cliente_id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(cliente_id):
    db_conn = get_db()
    
    # 1. Cargar lista de posibles apoderados (Necesario para el buscador en GET y POST)
    posibles_apoderados = []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Traemos solo clientes que NO sean dependientes (para evitar ciclos: hijo de su hijo)
            # Y excluimos al propio cliente que estamos editando
            cur.execute("""
                SELECT id, razon_social_nombres, apellidos, telefono 
                FROM clientes 
                WHERE apoderado_id IS NULL AND id != %s
                ORDER BY razon_social_nombres
            """, (cliente_id,))
            posibles_apoderados = cur.fetchall()
    except Exception as e:
        current_app.logger.error(f"Error cargando apoderados: {e}")

    if request.method == 'POST':
        # Recoger datos
        tipo_documento = request.form.get('tipo_documento')
        numero_documento = request.form.get('numero_documento', '').strip() or None
        razon_social_nombres = request.form.get('razon_social_nombres', '').strip().title()
        
        # Nuevos apellidos
        apellido_paterno = request.form.get('apellido_paterno', '').strip().title() or None
        apellido_materno = request.form.get('apellido_materno', '').strip().title() or None
        
        parts = []
        if apellido_paterno: parts.append(apellido_paterno)
        if apellido_materno: parts.append(apellido_materno)
        apellidos = " ".join(parts) if parts else None
        direccion = request.form.get('direccion', '').strip() or None
        email = request.form.get('email', '').strip() or None
        telefono = request.form.get('telefono', '').strip() or None
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        puntos_fidelidad = request.form.get('puntos_fidelidad', 0, type=int)
        
        # Campos nuevos
        genero = request.form.get('genero', 'Masculino').strip()
        preferencia_servicio = request.form.get('preferencia_servicio', 'Barberia').strip()

        # NUEVO: Apoderado
        apoderado_id = request.form.get('apoderado_id')
        if not apoderado_id or apoderado_id == '':
            apoderado_id = None

        errores = []
        if not razon_social_nombres: errores.append("El nombre es obligatorio.")
        
        # Validación de teléfono condicionada
        if not apoderado_id and not telefono:
            errores.append("El teléfono es obligatorio para clientes titulares.")

        fecha_nacimiento = None
        if fecha_nacimiento_str:
            try:
                fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()
            except ValueError:
                errores.append("Fecha inválida.")

        # Verificar duplicados (Excluyendo al propio cliente)
        if telefono:
            cursor_check = None
            try:
                cursor_check = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Verificar teléfono usado por OTRO cliente
                cursor_check.execute("""
                    SELECT id FROM clientes 
                    WHERE telefono = %s AND id != %s AND LOWER(razon_social_nombres) = LOWER(%s)
                """, (telefono, cliente_id, razon_social_nombres))
                
                if cursor_check.fetchone():
                    errores.append(f"El teléfono ya pertenece a otro cliente con el mismo nombre.")
            finally:
                if cursor_check: cursor_check.close()

        if errores:
            for err in errores: flash(err, 'warning')
            # Si hay error, necesitamos volver a mostrar el form con los datos enviados
            # Y recuperar el nombre del apoderado si se seleccionó uno
            nombre_apoderado_form = ""
            if apoderado_id:
                 # Buscar nombre solo para mostrarlo en el input al recargar por error
                 for apo in posibles_apoderados:
                     if str(apo['id']) == str(apoderado_id):
                         nombre_apoderado_form = f"{apo['razon_social_nombres']} {apo['apellidos'] or ''}"
                         break

            return render_template('clientes/form_cliente.html', 
                                   es_nueva=False, 
                                   titulo_form="Editar Cliente",
                                   action_url=url_for('main.editar_cliente', cliente_id=cliente_id),
                                   form_data=request.form,
                                   posibles_apoderados=posibles_apoderados,
                                   nombre_apoderado_actual=nombre_apoderado_form)

        # Actualizar
        cursor_update = None
        try:
            cursor_update = db_conn.cursor()
            sql_update = """UPDATE clientes SET 
                                tipo_documento=%s, numero_documento=%s, razon_social_nombres=%s, 
                                apellidos=%s, apellido_paterno=%s, apellido_materno=%s,
                                direccion=%s, email=%s, telefono=%s, 
                                fecha_nacimiento=%s, puntos_fidelidad=%s, apoderado_id=%s,
                                genero=%s, preferencia_servicio=%s
                            WHERE id=%s"""
            val_update = (tipo_documento, numero_documento, razon_social_nombres, apellidos, 
                          apellido_paterno, apellido_materno,
                          direccion, email, telefono, fecha_nacimiento, puntos_fidelidad, apoderado_id, 
                          genero, preferencia_servicio, cliente_id)
            
            cursor_update.execute(sql_update, val_update)
            db_conn.commit()
            flash('Cliente actualizado exitosamente.', 'success')
            return redirect(url_for('main.listar_clientes'))

        except Exception as e:
            db_conn.rollback()
            flash(f"Error al actualizar: {e}", "danger")
            return redirect(url_for('main.editar_cliente', cliente_id=cliente_id))
        finally:
            if cursor_update: cursor_update.close()
    
    # --- Lógica GET (Cargar datos actuales) ---
    cursor_get = None
    try:
        cursor_get = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_get.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
        cliente_actual = cursor_get.fetchone()
        
        if not cliente_actual:
            flash("Cliente no encontrado.", "warning")
            return redirect(url_for('main.listar_clientes'))
            
        # Formatear fecha
        if cliente_actual.get('fecha_nacimiento'):
            cliente_actual['fecha_nacimiento'] = cliente_actual['fecha_nacimiento'].strftime('%Y-%m-%d')
        
        # BUSCAR NOMBRE DEL APODERADO ACTUAL (Si tiene)
        nombre_apoderado_actual = ""
        if cliente_actual.get('apoderado_id'):
            cursor_get.execute("SELECT razon_social_nombres, apellidos FROM clientes WHERE id = %s", (cliente_actual['apoderado_id'],))
            apo_data = cursor_get.fetchone()
            if apo_data:
                nombre_apoderado_actual = f"{apo_data['razon_social_nombres']} {apo_data['apellidos'] or ''}"

        return render_template('clientes/form_cliente.html', 
                               es_nueva=False, 
                               titulo_form=f"Editar Cliente: {cliente_actual.get('razon_social_nombres')}",
                               action_url=url_for('main.editar_cliente', cliente_id=cliente_id),
                               cliente=cliente_actual,
                               form_data=cliente_actual,
                               posibles_apoderados=posibles_apoderados, # <--- LISTA PARA EL DATALIST
                               nombre_apoderado_actual=nombre_apoderado_actual) # <--- NOMBRE PARA EL INPUT
                               
    except Exception as e:
        flash(f"Error al cargar cliente: {e}", "danger")
        return redirect(url_for('main.listar_clientes'))
    finally:
        if cursor_get: cursor_get.close()


@main_bp.route('/clientes/eliminar/<int:cliente_id>', methods=['GET', 'POST']) # Idealmente POST
@login_required
def eliminar_cliente(cliente_id):
    try:
        db = get_db()
        cursor = db.cursor()

        sql = "DELETE FROM clientes WHERE id = %s"
        cursor.execute(sql, (cliente_id,))
        db.commit()
        
        if cursor.rowcount > 0:
            flash(f'Cliente eliminado exitosamente.', 'success')
        else:
            flash(f'No se encontró el cliente.', 'warning')
            
        cursor.close()

    except Exception as err:
        db.rollback()
        # Detección de error de clave foránea en Postgres (IntegrityError código 23503)
        err_msg = str(err)
        if '23503' in getattr(err, 'pgcode', '') or 'foreign key' in err_msg:
             flash('No se puede eliminar: El cliente tiene historial (ventas, citas, etc.).', 'warning')
        else:
             flash(f'Error al eliminar: {err}', 'danger')
        
        current_app.logger.error(f"Error eliminar_cliente {cliente_id}: {err}")

    return redirect(url_for('main.listar_clientes'))


# -------------------------------------------------------------------------
# API CAMPAÑA DE DATOS (ACTUALIZAR CUMPLEAÑOS)
# -------------------------------------------------------------------------
@main_bp.route('/api/clientes/actualizar-campana', methods=['POST'])
@login_required
def actualizar_cliente_campana():
    """
    Recibe la respuesta del cliente sobre sus datos (Confirmar, Actualizar o Rechazar).
    """
    data = request.get_json()
    cliente_id = data.get('cliente_id')
    accion = data.get('accion') # 'confirmar', 'actualizar', 'rechazar'
    fecha = data.get('fecha_nacimiento') # YYYY-MM-DD
    
    db_conn = get_db()
    try:
        with db_conn.cursor() as cursor:
            if accion == 'rechazar':
                # Cliente no quiere dar el dato -> Marcamos rechazo
                cursor.execute("""
                    UPDATE clientes 
                    SET rechazo_dato_cumpleanos = TRUE, 
                        cumpleanos_validado = TRUE -- Para que no vuelva a salir
                    WHERE id = %s
                """, (cliente_id,))
                msg = "Preferencia guardada. No se volverá a consultar."
                
            elif accion == 'confirmar':
                # Cliente confirma que el dato existente es correcto
                cursor.execute("""
                    UPDATE clientes SET cumpleanos_validado = TRUE WHERE id = %s
                """, (cliente_id,))
                msg = "¡Fecha confirmada exitosamente!"
                
            elif accion == 'actualizar':
                # Cliente da una nueva fecha
                if not fecha:
                    return jsonify({'success': False, 'message': 'Fecha inválida'})
                    
                cursor.execute("""
                    UPDATE clientes 
                    SET fecha_nacimiento = %s, 
                        cumpleanos_validado = TRUE,
                        rechazo_dato_cumpleanos = FALSE
                    WHERE id = %s
                """, (fecha, cliente_id))
                msg = "¡Datos actualizados correctamente!"
                
            else:
                return jsonify({'success': False, 'message': 'Acción no reconocida'})
                
            db_conn.commit()
            return jsonify({'success': True, 'message': msg})
            
    except Exception as e:
        db_conn.rollback()
        return jsonify({'success': False, 'message': str(e)})


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
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # CORRECCIÓN: Buscamos en la columna 'numero_documento'
            # y seleccionamos las columnas con los nombres nuevos.
            sql = "SELECT id, razon_social_nombres, apellidos, numero_documento FROM clientes WHERE numero_documento = %s"
            cursor.execute(sql, (numero_doc,))
            cliente = cursor.fetchone()

            if cliente:
                return jsonify(cliente)
            else:
                return jsonify({"error": "No se encontró un cliente con ese documento."}), 404
    
    except Exception as err:
        current_app.logger.error(f"Error DB en api_buscar_cliente_por_documento: {err}")
        return jsonify({"error": "Error interno al buscar el cliente."}), 500


# --- RUTAS PARA LA GESTIÓN DE CATEGORÍAS DE SERVICIOS ---

@main_bp.route('/servicios/categorias')
@login_required
def listar_categorias_servicios():
    """
    Muestra la lista de todas las categorías de servicios.
    """
    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion, activo FROM categorias_servicios ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        except Exception as err:
            db.rollback()
            # Error 23505 es para entrada duplicada (nombre UNIQUE)
            if '23505' in str(err):
                flash(f'Error: Ya existe una categoría con el nombre "{nombre}".', 'danger')
            else:
                flash(f'Error al registrar la categoría: {err}', 'danger')
            current_app.logger.error(f"Error en nueva_categoria_servicio (POST): {err}")
            cursor.close()
            return render_template('servicios/form_categoria.html', form_data=request.form, es_nueva=True, titulo_form="Nueva Categoría")

    # Método GET: muestra el formulario vacío para una nueva categoría
    return render_template('servicios/form_categoria.html', es_nueva=True, titulo_form="Registrar Nueva Categoría de Servicio")

@main_bp.route('/servicios/categorias/toggle/<int:categoria_id>', methods=['POST'])
@login_required
def toggle_categoria_servicio(categoria_id):
    """
    Alterna el estado activo/inactivo de una categoría.
    """
    try:
        db = get_db()
        cursor = db.cursor()
        # Usamos NOT activo para invertir el valor actual
        cursor.execute("UPDATE categorias_servicios SET activo = NOT activo WHERE id = %s RETURNING activo", (categoria_id,))
        resultado = cursor.fetchone()
        
        if resultado is None:
             return jsonify({'success': False, 'message': 'Categoría no encontrada'}), 404
             
        nuevo_estado = resultado[0]
        db.commit()
        cursor.close()
        
        return jsonify({'success': True, 'nuevo_estado': nuevo_estado})
    except Exception as e:
        if db: db.rollback()
        current_app.logger.error(f"Error al cambiar estado de categoría {categoria_id}: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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
        cursor_check = db_check.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_check.execute("SELECT id, nombre, descripcion FROM categorias_servicios WHERE id = %s", (categoria_id,))
        categoria_actual = cursor_check.fetchone()
        cursor_check.close()
    except Exception as err:
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
        except Exception as err:
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

    except Exception as err:
        db.rollback() # Revertir en caso de error
        flash(f'Error al eliminar la categoría: {err}', 'danger')
        current_app.logger.error(f"Error DB en eliminar_categoria_servicio (ID: {categoria_id}): {err}")
        # Si el error es por una restricción de clave foránea (ej. servicios aún la usan)
        if '23503' in str(err): # Error PostgreSQL 23503: foreign key violation
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    except Exception as err:
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
        cursor_cat = db_cat.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_cat.execute("SELECT id, nombre FROM categorias_servicios ORDER BY nombre")
        categorias = cursor_cat.fetchall()
        # No cerramos la conexión principal (g.db) aquí, solo el cursor si es necesario.
        # teardown_db se encargará de cerrar g.db al final de la petición.
        cursor_cat.close() 
    except Exception as err:
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
        except Exception as err:
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
    cursor_servicio = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor_servicio.execute("SELECT * FROM servicios WHERE id = %s", (servicio_id,))
        servicio_actual = cursor_servicio.fetchone()
    except Exception as err:
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
    cursor_categorias = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cursor_categorias.execute("SELECT id, nombre FROM categorias_servicios ORDER BY nombre")
        categorias = cursor_categorias.fetchall()
    except Exception as err:
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
            
        except Exception as err:
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
        cursor_read = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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
    Muestra la lista de todos los colaboradores con sus sucursales asignadas.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Consulta SQL actualizada para obtener una lista de sucursales por empleado
            sql = """
                SELECT 
                    e.id, e.nombres, e.apellidos, e.nombre_display, e.dni, 
                    e.email, e.telefono, e.activo, e.sueldo_base,
                    TO_CHAR(e.fecha_contratacion, 'DD/MM/YYYY') as fecha_contratacion_formateada,
                    r.nombre AS rol_nombre,
                    string_agg(s.nombre, ', ') AS sucursales_nombres
                FROM empleados e
                LEFT JOIN roles r ON e.rol_id = r.id
                LEFT JOIN empleado_sucursales es ON e.id = es.empleado_id
                LEFT JOIN sucursales s ON es.sucursal_id = s.id
                GROUP BY e.id, r.nombre
                ORDER BY e.apellidos, e.nombres
            """
            cursor.execute(sql)
            lista_de_empleados = cursor.fetchall()
    except Exception as err:
        flash(f"Error al acceder a los colaboradores: {err}", "danger")
        current_app.logger.error(f"Error en listar_empleados: {err}")
        lista_de_empleados = []
        
    return render_template('empleados/lista_empleados.html', empleados=lista_de_empleados)


@main_bp.route('/empleados/nuevo', methods=['GET', 'POST'])
@login_required
# @admin_required  <-- Asegúrate de tener este decorador importado o coméntalo si da error
def nuevo_empleado():
    """
    Muestra el formulario para registrar un nuevo colaborador (GET)
    y procesa la creación con todos los nuevos campos (POST).
    """
    db_conn = get_db()
    
    # 1. CARGA DE DATOS MAESTROS (Sucursales y Roles)
    # Es necesario cargarlos SIEMPRE (tanto para GET como para POST si hay error)
    sucursales_activas = []
    roles_disponibles = [] # <--- NUEVA LISTA PARA ROLES
    
    cursor_maestros = None
    try:
        cursor_maestros = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Cargar Sucursales
        cursor_maestros.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor_maestros.fetchall()
        
        # Cargar Roles (ESTO FALTABA)
        cursor_maestros.execute("SELECT id, nombre FROM roles ORDER BY nombre")
        roles_disponibles = cursor_maestros.fetchall()
        
    except Exception as err_load:
        flash(f"Error al cargar datos maestros: {err_load}", "danger")
        current_app.logger.error(f"Error DB cargando maestros en nuevo_empleado: {err_load}")
    finally:
        if cursor_maestros: cursor_maestros.close()


    form_titulo = "Registrar Nuevo Colaborador"
    action_url_form = url_for('main.nuevo_empleado')

    if request.method == 'POST':
        # Recoger campos
        nombres = request.form.get('nombres')
        apellidos = request.form.get('apellidos')
        nombre_display = request.form.get('nombre_display', '').strip()
        dni = request.form.get('dni', '').strip()
        fecha_nacimiento_str = request.form.get('fecha_nacimiento')
        email = request.form.get('email', '').strip()
        telefono = request.form.get('telefono', '').strip()
        rol_id = request.form.get('rol_id')
        sueldo_base_str = request.form.get('sueldo_base')
        # ---> NUEVO: Obtenemos la lista de sucursales
        sucursales_ids_seleccionadas = request.form.getlist('sucursales_ids', type=int)
        fecha_contratacion_str = request.form.get('fecha_contratacion')
        activo = 'activo' in request.form
        notas = request.form.get('notas')
        password_nuevo = request.form.get('password_nuevo')

        # ---> NUEVOS CAMPOS CONTRATO/COMISION
        tipo_contrato = request.form.get('tipo_contrato', 'FIJO')
        realiza_servicios = 'realiza_servicios' in request.form
        realiza_ventas = 'realiza_ventas' in request.form
        porcentaje_comision_productos_str = request.form.get('porcentaje_comision_productos')
        porcentaje_comision_productos = float(porcentaje_comision_productos_str) if porcentaje_comision_productos_str else 0.00
        
        # Construir JSON de configuración
        configuracion_comision = {}
        if tipo_contrato == 'MIXTO':
            configuracion_comision = {
                'meta': float(request.form.get('mixto_meta') or 0),
                'porcentaje': float(request.form.get('mixto_porcentaje') or 0)
            }
        elif tipo_contrato == 'ESCALONADA':
            escalonada_json = request.form.get('escalonada_json')
            if escalonada_json:
                try:
                    configuracion_comision = json.loads(escalonada_json)
                except Exception:
                    configuracion_comision = {}

        # Validaciones (igual que antes)
        errores = []
        if not nombres: errores.append('El nombre es obligatorio.')
        if not apellidos: errores.append('Los apellidos son obligatorios.')
        if not rol_id: errores.append('El rol es obligatorio.')
        
        if not nombre_display:
            primer_nombre = nombres.split(' ')[0]
            primer_apellido = apellidos.split(' ')[0]
            nombre_display = f"{primer_nombre} {primer_apellido}"
            
        fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date() if fecha_nacimiento_str else None
        fecha_contratacion = datetime.strptime(fecha_contratacion_str, '%Y-%m-%d').date() if fecha_contratacion_str else None
        dni_db = dni if dni else None
        email_db = email if email else None
        sueldo_base = float(sueldo_base_str) if sueldo_base_str else 0.00

        if dni_db:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor_check:
                cursor_check.execute("SELECT id FROM empleados WHERE dni = %s", (dni_db,))
                if cursor_check.fetchone():
                    errores.append(f"El DNI '{dni_db}' ya está registrado.")

        if errores:
            for error in errores: flash(error, 'warning')
            return render_template('empleados/form_empleado.html', 
                                   form_data=request.form, 
                                   sucursales=sucursales_activas,
                                   roles=roles_disponibles,
                                   sucursales_asignadas=sucursales_ids_seleccionadas, # Re-seleccionar en error
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)
        
        # ---> LÓGICA DE INSERCIÓN MODIFICADA
        try:
            with db_conn.cursor() as cursor:
                # 1. Insertar en 'empleados' (sin sucursal_id) y obtener el ID del nuevo empleado
                if password_nuevo:
                    hashed_password = generate_password_hash(password_nuevo)

                sql_empleado = """INSERT INTO empleados 
                                    (nombres, apellidos, nombre_display, dni, fecha_nacimiento, email, telefono, 
                                     rol_id, sueldo_base, fecha_contratacion, activo, notas, password,
                                     tipo_contrato, realiza_servicios, realiza_ventas, porcentaje_comision_productos, configuracion_comision)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""
                
                val_empleado = (nombres, apellidos, nombre_display, dni_db, fecha_nacimiento, email_db, 
                                (telefono if telefono else None), rol_id, sueldo_base,
                                fecha_contratacion, activo, (notas if notas else None), hashed_password,
                                tipo_contrato, realiza_servicios, realiza_ventas, porcentaje_comision_productos, json.dumps(configuracion_comision))
                
                cursor.execute(sql_empleado, val_empleado)
                nuevo_empleado_id = cursor.fetchone()[0] # Obtenemos el ID retornado

                # 2. Insertar las asignaciones en 'empleado_sucursales'
                if sucursales_ids_seleccionadas:
                    sql_asignacion = "INSERT INTO empleado_sucursales (empleado_id, sucursal_id) VALUES (%s, %s)"
                    valores_asignacion = [(nuevo_empleado_id, suc_id) for suc_id in sucursales_ids_seleccionadas]
                    for val in valores_asignacion:
                        cursor.execute(sql_asignacion, val)

            db_conn.commit()
            flash(f'Colaborador {nombres} {apellidos} registrado exitosamente!', 'success')
            return redirect(url_for('main.listar_empleados'))
            
        except Exception as err:
            db_conn.rollback()
            error_msg = str(err)
            if '23505' in getattr(err, 'pgcode', '') or 'duplicate key' in error_msg:
                if 'dni' in error_msg: flash(f'Error: Ya existe un colaborador con el DNI "{dni_db}".', 'danger')
                elif 'email' in error_msg: flash(f'Error: Ya existe un colaborador con el email "{email_db}".', 'danger')
                else: flash('Error: Datos duplicados en el sistema.', 'danger')
            else:
                flash(f'Error al registrar: {err}', 'danger')
                
            current_app.logger.error(f"Error insertando empleado: {err}")
            
            return render_template('empleados/form_empleado.html', 
                                   form_data=request.form, 
                                   sucursales=sucursales_activas,
                                   roles=roles_disponibles,
                                   sucursales_asignadas=sucursales_ids_seleccionadas,
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

    # Método GET
    return render_template('empleados/form_empleado.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           sucursales=sucursales_activas,
                           roles=roles_disponibles,
                           sucursales_asignadas=[]) # <-- Pasar lista vacía para 'nuevo'


@main_bp.route('/empleados/editar/<int:empleado_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_empleado(empleado_id):
    """
    Maneja la edición de un colaborador, asegurando que los datos del formulario
    se conserven si la validación falla.
    """
    db_conn = get_db()

    # --- 1. OBTENER DATOS MAESTROS (se necesitan siempre) ---
    roles_disponibles, sucursales_activas = [], []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM roles ORDER BY nombre")
            roles_disponibles = cursor.fetchall()
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
    except Exception as e:
        flash(f"Error crítico al cargar datos maestros: {e}", "danger")
        return redirect(url_for('main.listar_empleados'))

    # --- 2. OBTENER COLABORADOR (si no existe, no continuar) ---
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM empleados WHERE id = %s", (empleado_id,))
        colaborador_actual = cursor.fetchone()
    if not colaborador_actual:
        flash(f"Colaborador con ID {empleado_id} no encontrado.", "warning")
        return redirect(url_for('main.listar_empleados'))

    # --- 3. LÓGICA POST: Procesar el formulario ---
    if request.method == 'POST':
        # Recoger la lista de sucursales seleccionadas del formulario
        sucursales_ids_seleccionadas = request.form.getlist('sucursales_ids', type=int)
        
        try:
            # Recoger todos los demás datos del formulario
            nombres = request.form.get('nombres')
            apellidos = request.form.get('apellidos')
            nombre_display = request.form.get('nombre_display', '').strip() or f"{nombres.split(' ')[0]} {apellidos.split(' ')[0]}"
            dni_nuevo = request.form.get('dni', '').strip() or None
            fecha_nacimiento_str = request.form.get('fecha_nacimiento')
            email_nuevo = request.form.get('email', '').strip() or None
            telefono = request.form.get('telefono', '').strip() or None
            rol_id = request.form.get('rol_id', type=int)
            sueldo_base_str = request.form.get('sueldo_base')
            fecha_contratacion_str = request.form.get('fecha_contratacion')
            activo_nuevo = 'activo' in request.form
            notas = request.form.get('notas', '').strip() or None
            password_nuevo = request.form.get('password_nuevo')
            password_confirmacion = request.form.get('password_confirmacion')

            # ---> NUEVOS CAMPOS CONTRATO/COMISION
            tipo_contrato = request.form.get('tipo_contrato', 'FIJO')
            realiza_servicios = 'realiza_servicios' in request.form
            realiza_ventas = 'realiza_ventas' in request.form
            porcentaje_comision_productos_str = request.form.get('porcentaje_comision_productos')
            porcentaje_comision_productos = float(porcentaje_comision_productos_str) if porcentaje_comision_productos_str else 0.00
            
            # Construir JSON de configuración (igual que en nuevo)
            configuracion_comision = {}
            if tipo_contrato == 'MIXTO':
                configuracion_comision = {
                    'meta': float(request.form.get('mixto_meta') or 0),
                    'porcentaje': float(request.form.get('mixto_porcentaje') or 0)
                }
            elif tipo_contrato == 'ESCALONADA':
                escalonada_json = request.form.get('escalonada_json')
                if escalonada_json:
                    try:
                        configuracion_comision = json.loads(escalonada_json)
                    except Exception:
                        configuracion_comision = {}

            # Validaciones
            errores = []
            if not all([nombres, apellidos, rol_id]):
                errores.append("Nombres, Apellidos y Rol son campos obligatorios.")

            if dni_nuevo and dni_nuevo != colaborador_actual.get('dni'):
                with db_conn.cursor() as cursor_check:
                    cursor_check.execute("SELECT id FROM empleados WHERE dni = %s AND id != %s", (dni_nuevo, empleado_id))
                    if cursor_check.fetchone():
                        errores.append(f"El DNI '{dni_nuevo}' ya está registrado.")
            
            if email_nuevo and email_nuevo.lower() != (colaborador_actual.get('email') or '').lower():
                 with db_conn.cursor() as cursor_check:
                    cursor_check.execute("SELECT id FROM empleados WHERE lower(email) = lower(%s) AND id != %s", (email_nuevo, empleado_id))
                    if cursor_check.fetchone():
                        errores.append(f"El email '{email_nuevo}' ya está registrado.")

            password_hash_para_guardar = None
            if password_nuevo:
                if password_nuevo != password_confirmacion:
                    errores.append("Las contraseñas no coinciden.")
                elif len(password_nuevo) < 8:
                    errores.append("La contraseña debe tener al menos 8 caracteres.")
                else:
                    password_hash_para_guardar = generate_password_hash(password_nuevo)
            
            if errores: raise ValueError("; ".join(errores))

            # --- Lógica de actualización en la BD ---
            # --- Lógica de actualización en la BD ---
            with db_conn.cursor() as cursor:
                # 1. Actualizar la tabla principal 'empleados'
                sql_base = """UPDATE empleados SET nombres=%s, apellidos=%s, nombre_display=%s, dni=%s, 
                              fecha_nacimiento=%s, email=%s, telefono=%s, rol_id=%s, sueldo_base=%s, 
                              fecha_contratacion=%s, activo=%s, notas=%s,
                              tipo_contrato=%s, realiza_servicios=%s, realiza_ventas=%s, porcentaje_comision_productos=%s, configuracion_comision=%s
                           """
                params = [nombres, apellidos, nombre_display, dni_nuevo, (fecha_nacimiento_str or None), email_nuevo, telefono, rol_id, 
                          (float(sueldo_base_str) if sueldo_base_str else 0.00), (fecha_contratacion_str or None), activo_nuevo, notas,
                          tipo_contrato, realiza_servicios, realiza_ventas, porcentaje_comision_productos, json.dumps(configuracion_comision)]
                
                if password_hash_para_guardar:
                    sql_base += ", password = %s"
                    params.append(password_hash_para_guardar)
                
                sql_final = sql_base + " WHERE id = %s"
                params.append(empleado_id)
                cursor.execute(sql_final, tuple(params))

                # 2. Gestionar las asignaciones en 'empleado_sucursales'
                cursor.execute("DELETE FROM empleado_sucursales WHERE empleado_id = %s", (empleado_id,))
                if sucursales_ids_seleccionadas:
                    sql_asignacion = "INSERT INTO empleado_sucursales (empleado_id, sucursal_id) VALUES (%s, %s)"
                    for suc_id in sucursales_ids_seleccionadas:
                        cursor.execute(sql_asignacion, (empleado_id, suc_id))

            db_conn.commit()
            flash('Colaborador actualizado exitosamente!', 'success')
            return redirect(url_for('main.listar_empleados'))

        except (ValueError, psycopg2.Error) as e:
            db_conn.rollback()
            if isinstance(e, ValueError):
                flash(str(e), "warning")
            else:
                flash(f"Error de base de datos al actualizar: {e}", "danger")
            
            # --- Re-renderizar el formulario con los datos del POST fallido ---
            return render_template('empleados/form_empleado.html', 
                                   es_nueva=False, 
                                   titulo_form=f"Editar Colaborador: {colaborador_actual.get('nombres')}",
                                   action_url=url_for('main.editar_empleado', empleado_id=empleado_id),
                                   empleado=colaborador_actual,
                                   roles=roles_disponibles,
                                   sucursales=sucursales_activas,
                                   form_data=request.form, # <-- Datos del formulario que falló
                                   sucursales_asignadas=sucursales_ids_seleccionadas) # <-- Sucursales del formulario

    # --- 4. LÓGICA GET: Mostrar el formulario por primera vez ---
    sucursales_asignadas_ids = []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT sucursal_id FROM empleado_sucursales WHERE empleado_id = %s", (empleado_id,))
            sucursales_asignadas_ids = [row['sucursal_id'] for row in cursor.fetchall()]
    except Exception as e:
        flash(f"Error al cargar sucursales asignadas: {e}", "danger")

    # Formatear fechas para los inputs del formulario
    if colaborador_actual.get('fecha_nacimiento'):
        colaborador_actual['fecha_nacimiento'] = colaborador_actual['fecha_nacimiento'].strftime('%Y-%m-%d')
    if colaborador_actual.get('fecha_contratacion'):
        colaborador_actual['fecha_contratacion'] = colaborador_actual['fecha_contratacion'].strftime('%Y-%m-%d')
        
    return render_template('empleados/form_empleado.html', 
                           es_nueva=False, 
                           titulo_form=f"Editar Colaborador: {colaborador_actual.get('nombres')}",
                           action_url=url_for('main.editar_empleado', empleado_id=empleado_id),
                           empleado=colaborador_actual, # <-- Datos de la BD
                           roles=roles_disponibles,
                           sucursales=sucursales_activas,
                           sucursales_asignadas=sucursales_asignadas_ids, # <-- Sucursales de la BD
                           form_data=colaborador_actual)
                            

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
        cursor_read = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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
        except Exception as err:
            db_conn.rollback()
            if '23505' in str(err):
                flash(f"Error: Ya existe una cuota para este colaborador en {mes}/{anio}.", "danger")
            else:
                flash(f"Error de base de datos: {err}", "danger")
        except ValueError as ve:
            flash(f"Error de validación: {ve}", "warning")
        
        return redirect(url_for('main.gestionar_cuotas', colaborador_id=colaborador_id))

    # --- Lógica GET (para mostrar la página) ---
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
            colaborador = cursor.fetchone()
            if not colaborador:
                flash("Colaborador no encontrado.", "warning")
                return redirect(url_for('main.listar_empleados'))

            cursor.execute("SELECT * FROM cuotas_mensuales WHERE colaborador_id = %s ORDER BY anio DESC, mes DESC", (colaborador_id,))
            cuotas_registradas = cursor.fetchall()
    except Exception as err:
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
    except Exception as err:
        db_conn.rollback()
        if '23505' in str(err): # Error de constraint UNIQUE
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
    except Exception as err:
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
    except Exception as err:
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
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
        colaborador = cursor.fetchone()
        if not colaborador:
            flash("Colaborador no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        cursor.execute("SELECT *, TO_CHAR(fecha, 'DD/MM/YYYY') as fecha_formateada FROM ajustes_pago WHERE colaborador_id = %s ORDER BY fecha DESC, id DESC", (colaborador_id,))
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
    except Exception as err:
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
    except Exception as err:
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
    except Exception as err:
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
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Obtener lista de reservas (sin cambios)
            sql = "SELECT r.id, TO_CHAR(r.fecha_hora_inicio, 'DD/MM/YYYY') as fecha_hora, CONCAT(c.razon_social_nombres, ' ', COALESCE(c.apellidos, '')) AS cliente_nombre, e.nombre_display AS empleado_nombre, s.nombre AS servicio_nombre, r.precio_cobrado, r.estado FROM reservas r LEFT JOIN clientes c ON r.cliente_id = c.id JOIN empleados e ON r.empleado_id = e.id JOIN servicios s ON r.servicio_id = s.id ORDER BY r.fecha_hora_inicio DESC"
            cursor.execute(sql)
            lista_de_reservas = cursor.fetchall()

            # Obtener listas para los modales
            cursor.execute("SELECT id, razon_social_nombres, apellidos FROM clientes ORDER BY razon_social_nombres, apellidos")
            clientes_todos = cursor.fetchall()
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            empleados_para_selector = cursor.fetchall()
            cursor.execute("SELECT id, nombre, duracion_minutos FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_todos_activos = cursor.fetchall()

    except Exception as err:
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
    FILTRADO: Solo muestra datos de la sucursal actual del usuario.
    """
    db_conn = get_db()
    clientes_todos, servicios_todos_activos, empleados_para_selector = [], [], []
    
    # 1. Obtener y Validar Sucursal de la Sesión
    sucursal_id = session.get('sucursal_id')
    if not sucursal_id:
        flash("Debes seleccionar una sucursal para ver la agenda.", "warning")
        return redirect(url_for('main.index'))

    try:
        # 2. Obtener Nombre de la Sucursal (Para mostrar en el título)
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT nombre FROM sucursales WHERE id = %s", (sucursal_id,))
            res_suc = cursor.fetchone()
            session['sucursal_nombre'] = res_suc['nombre'] if res_suc else 'Desconocida'

        # 3. Datos Maestros Ligeros (Servicios)
        # Clientes YA NO se cargan aquí para mejorar velocidad (se usa API Búsqueda)
        clientes_todos = [] 

        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre, precio, duracion_minutos FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios_todos_activos = cursor.fetchall()

        # 4. Cargar Colaboradores (OPTIMIZADO - Solo datos base)
        # Quitamos los counts y subqueries pesadas. El frontend las pedirá vía API si necesita.
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""
                SELECT e.id, e.nombres, e.apellidos, e.nombre_display, NULL as foto
                FROM empleados e
                WHERE e.activo = TRUE 
                  AND e.realiza_servicios = TRUE  
                  AND e.id IN (SELECT empleado_id FROM empleado_sucursales WHERE sucursal_id = %s)
                ORDER BY e.apellidos, e.nombres
            """, (sucursal_id,))
            empleados_para_selector = cursor.fetchall()

    except Exception as err_load:
        if db_conn:
            db_conn.rollback()
        flash(f"Error fatal al cargar datos maestros para la agenda: {err_load}", "danger")
    
    return render_template('reservas/agenda_diaria.html', 
                           clientes_todos=clientes_todos, # Enviamos lista vacía
                           servicios_todos_activos=servicios_todos_activos,
                           empleados_para_selector=empleados_para_selector)

@main_bp.route('/api/clientes/buscar', methods=['GET'])
@login_required
def api_buscar_clientes():
    """
    API para búsqueda de clientes via AJAX (Select2).
    Optimizado para devolver resultados rápidos.
    """
    search_term = request.args.get('q', '').strip()
    if not search_term or len(search_term) < 2:
        return jsonify({"results": []})
        
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Búsqueda por Nombre o Documento o Teléfono
            query = """
                SELECT id, razon_social_nombres, apellidos, numero_documento, telefono
                FROM clientes
                WHERE 
                    razon_social_nombres ILIKE %s OR
                    apellidos ILIKE %s OR
                    numero_documento ILIKE %s OR
                    telefono ILIKE %s
                ORDER BY razon_social_nombres
                LIMIT 20
            """
            term = f"%{search_term}%"
            cursor.execute(query, (term, term, term, term))
            clientes = cursor.fetchall()
            
            results = []
            for c in clientes:
                nombre = f"{c['razon_social_nombres']} {c.get('apellidos') or ''}".strip()
                doc = c.get('numero_documento') or 'S/D'
                results.append({
                    "id": c['id'],
                    "text": f"{nombre} (Doc: {doc})"
                })
                
            return jsonify({"results": results})
            
    except Exception as e:
        current_app.logger.error(f"Error buscando clientes: {e}")
        return jsonify({"results": []})   
    
@main_bp.route('/api/reservas/<int:reserva_id>')
@login_required
def api_get_datos_reserva(reserva_id):
    """
    API para obtener los detalles completos de una reserva específica
    para mostrar en el modal de gestión.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Consulta actualizada para usar la nueva estructura de la tabla 'clientes'
            sql = """
                SELECT r.*, s.nombre as servicio_nombre, e.nombre_display as empleado_nombre_completo,
                    CONCAT(c.razon_social_nombres, ' ', COALESCE(c.apellidos, '')) as cliente_nombre_completo
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
    
    except Exception as err:
        current_app.logger.error(f"Error DB en api_get_datos_reserva: {err}")
        return jsonify({"error": "Error interno al buscar la reserva."}), 500


@main_bp.route('/api/agenda_dia_data')
@login_required
def api_agenda_dia_data():
    """
    API Corregida: Carga agenda sin buscar la columna 'foto' para evitar errores.
    """
    fecha_str = request.args.get('fecha', date.today().isoformat())
    sucursal_id = request.args.get('sucursal_id', type=int)
    
    if not sucursal_id:
        return jsonify({"recursos": [], "eventos": []})
        
    try:
        fecha_obj = date.fromisoformat(fecha_str)
    except ValueError:
        return jsonify({"error": "Formato de fecha inválido"}), 400

    try:
        db_conn = get_db()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            
            # --- 1. OBTENER RECURSOS (COLABORADORES) ---
            # 🟢 CORRECCIÓN: Quitamos reference a 'e.foto' porque no existe en la BD
            # 1.A. Pre-calcular quienes tienen turno este día (Optimización: 1 sola query en lugar de N)
            # Buscamos IDs que tengan horarios_empleado (día semana) O horarios_extra (fecha exacta)
            dia_semana_num = fecha_obj.isoweekday()
            
            cursor.execute("""
                SELECT DISTINCT empleado_id 
                FROM horarios_empleado 
                WHERE dia_semana = %s
                UNION
                SELECT DISTINCT empleado_id 
                FROM horarios_extra 
                WHERE fecha = %s
            """, (dia_semana_num, fecha_str))
            
            ids_con_turno = {row['empleado_id'] for row in cursor.fetchall()}

            # --- 1.B. QUERY PRINCIPAL DE EMPLEADOS (OPTIMIZADA) ---
            # Usamos LEFT JOIN con una subquery pre-agrupada en lugar de una subquery correlacionada por cada fila.
            cursor.execute("""
                SELECT e.id, e.nombre_display as title,
                       COALESCE(citas.total, 0) as citas_hoy_count
                FROM empleados e
                LEFT JOIN (
                    SELECT empleado_id, COUNT(*) as total
                    FROM reservas 
                    WHERE DATE(fecha_hora_inicio) = %s
                      AND estado NOT IN ('Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio')
                    GROUP BY empleado_id
                ) citas ON e.id = citas.empleado_id
                WHERE e.activo = TRUE 
                  AND e.realiza_servicios = TRUE  
                  AND e.id IN (SELECT empleado_id FROM empleado_sucursales WHERE sucursal_id = %s)
                ORDER BY e.nombres
            """, (fecha_str, sucursal_id))
            
            recursos_db = cursor.fetchall()
            
            recursos = []
            for r in recursos_db:
                recursos.append({
                    "id": r['id'],
                    "title": r['title'],
                    "imagen_url": None,
                    "tiene_turno": (r['id'] in ids_con_turno),
                    "citas_hoy": r['citas_hoy_count']
                })
            
            eventos = []
            
            if recursos:
                recursos_ids = [r['id'] for r in recursos]
                
                placeholders = ','.join(['%s'] * len(recursos_ids))
                params_base = list(recursos_ids)
                
                # --- 2. HORARIOS (FONDO BLANCO) ---
                dia_semana_num = fecha_obj.isoweekday()
                
                sql_turnos = f"""
                    SELECT empleado_id, hora_inicio, hora_fin 
                    FROM horarios_empleado 
                    WHERE empleado_id IN ({placeholders}) AND dia_semana = %s
                """
                cursor.execute(sql_turnos, params_base + [dia_semana_num])
                
                for turno in cursor.fetchall():
                    eventos.append({
                        "resourceId": turno['empleado_id'],
                        "start": f"{fecha_str}T{turno['hora_inicio']}", 
                        "end": f"{fecha_str}T{turno['hora_fin']}",
                        "display": "background", 
                        # "backgroundColor": "#ffffff", REMOVED
                        "classNames": ["turno-disponible"]
                    })
                
                # --- 2.1 HORARIOS EXTRA (Turnos Adicionales) ---
                sql_extras = f"""
                    SELECT empleado_id, hora_inicio, hora_fin, motivo
                    FROM horarios_extra
                    WHERE empleado_id IN ({placeholders}) AND fecha = %s
                """
                cursor.execute(sql_extras, params_base + [fecha_str])
                
                for extra in cursor.fetchall():
                     eventos.append({
                        "resourceId": extra['empleado_id'],
                        "start": f"{fecha_str}T{extra['hora_inicio']}", 
                        "end": f"{fecha_str}T{extra['hora_fin']}",
                        "display": "background", 
                        # "backgroundColor": "#ffffff", REMOVED
                        "classNames": ["turno-disponible", "turno-extra"],
                        "title": f"Extra: {extra.get('motivo','')}"
                    })
                
                # --- 3. AUSENCIAS (FONDO ROJO) ---
                sql_ausencias = f"""
                    SELECT empleado_id, fecha_hora_inicio, fecha_hora_fin 
                    FROM ausencias_empleado 
                    WHERE empleado_id IN ({placeholders}) 
                      AND aprobado = TRUE 
                      AND DATE(fecha_hora_inicio) <= %s 
                      AND DATE(fecha_hora_fin) >= %s
                """
                cursor.execute(sql_ausencias, params_base + [fecha_str, fecha_str])
                
                for ausencia in cursor.fetchall():
                    eventos.append({
                        "resourceId": ausencia['empleado_id'],
                        "start": ausencia['fecha_hora_inicio'].isoformat(),
                        "end": ausencia['fecha_hora_fin'].isoformat(),
                        "display": "background", 
                        # "backgroundColor": "rgba(220, 53, 69, 0.5)", REMOVED
                        "classNames": ["bg-danger-subtle"], # To match CSS selector
                        "title": "Ausente"
                    })
                
                # --- 4. RESERVAS (TARJETAS) ---
                sql_reservas = """
                    SELECT 
                        r.id, 
                        r.fecha_hora_inicio as start, 
                        r.fecha_hora_fin as end, 
                        r.estado, 
                        r.empleado_id as "resourceId", 
                        CONCAT(s.nombre, ' - ', c.razon_social_nombres) as title 
                    FROM reservas r 
                    JOIN servicios s ON r.servicio_id = s.id 
                    LEFT JOIN clientes c ON r.cliente_id = c.id 
                    WHERE r.sucursal_id = %s 
                      AND DATE(r.fecha_hora_inicio) = %s 
                      AND r.estado NOT IN ('Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio')
                """
                cursor.execute(sql_reservas, (sucursal_id, fecha_str))
                
                for reserva in cursor.fetchall():
                    # Colors handled by CSS now
                    
                    eventos.append({
                        "id": reserva['id'],
                        "resourceId": reserva['resourceId'],
                        "title": reserva['title'],
                        "start": reserva['start'].isoformat(),
                        "end": reserva['end'].isoformat(),
                        # "backgroundColor": color_fondo, REMOVED
                        # "borderColor": border_color, REMOVED
                        # "textColor": "#fff", REMOVED
                        "extendedProps": {"estado": reserva['estado']}, # IMPORTANT for JS class logic
                        "classNames": ["reserva-card"]
                    })

    except Exception as e:
        current_app.logger.error(f"Error fatal en api_agenda_dia_data: {e}", exc_info=True)
        return jsonify({"error": "Error interno del servidor."}), 500

    return jsonify({"recursos": recursos, "eventos": eventos})

@main_bp.route('/api/agenda/bloquear', methods=['POST'])
@login_required
def api_agenda_bloquear():
    """
    Crea una ausencia (bloqueo) de horas para un empleado.
    """
    try:
        data = request.json
        empleado_id = data.get('empleado_id')
        fecha = data.get('fecha')
        hora_inicio = data.get('hora_inicio')
        hora_fin = data.get('hora_fin')
        motivo = data.get('motivo', 'Bloqueo Manual')
        
        if not all([empleado_id, fecha, hora_inicio, hora_fin]):
            return jsonify({"success": False, "message": "Faltan datos obligatorios."}), 400

        dt_inicio = f"{fecha} {hora_inicio}:00"
        dt_fin = f"{fecha} {hora_fin}:00"

        db = get_db()
        cursor = db.cursor()
        
        # Insertar en ausencias_empleado
        sql = """
            INSERT INTO ausencias_empleado 
            (empleado_id, tipo_ausencia, fecha_hora_inicio, fecha_hora_fin, descripcion, aprobado)
            VALUES (%s, 'Bloqueo Agenda', %s, %s, %s, TRUE) 
            RETURNING id
        """ 
        cursor.execute(sql, (empleado_id, dt_inicio, dt_fin, motivo))
        db.commit()
        
        return jsonify({"success": True, "message": "Horario bloqueado correctamente."})
        
    except Exception as e:
        if 'db' in locals(): db.rollback()
        current_app.logger.error(f"Error en api_agenda_bloquear: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@main_bp.route('/api/agenda/habilitar', methods=['POST'])
@login_required
def api_agenda_habilitar():
    """
    Crea un turno extra (horario habilitado) para un empleado.
    """
    try:
        data = request.json
        empleado_id = data.get('empleado_id')
        fecha = data.get('fecha')
        hora_inicio = data.get('hora_inicio')
        hora_fin = data.get('hora_fin')
        motivo = data.get('motivo', 'Habilitación Manual')
        sucursal_id = session.get('sucursal_id')
        
        if not all([empleado_id, fecha, hora_inicio, hora_fin]):
            return jsonify({"success": False, "message": "Faltan datos obligatorios."}), 400

        db = get_db()
        cursor = db.cursor()
        
        sql = """
            INSERT INTO horarios_extra 
            (empleado_id, sucursal_id, fecha, hora_inicio, hora_fin, motivo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (empleado_id, sucursal_id, fecha, hora_inicio, hora_fin, motivo))
        db.commit()
        
        return jsonify({"success": True, "message": "Horario habilitado correctamente."})

    except Exception as e:
        if 'db' in locals(): db.rollback()
        current_app.logger.error(f"Error en api_agenda_habilitar: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
   
    
    
    
import psycopg2.extras

@main_bp.route('/api/configuracion', methods=['GET', 'POST'])
@login_required
def api_configuracion():
    """
    GET: Devuelve la configuración de la sucursal actual (o valores por defecto).
    POST: Guarda/Actualiza la configuración.
    """
    sucursal_id = session.get('sucursal_id')
    current_app.logger.info(f"API Configuración solicitada. Sucursal: {sucursal_id}, Método: {request.method}")

    if not sucursal_id:
        return jsonify({"success": False, "message": "No hay sucursal seleccionada"}), 400

    db = get_db()
    if not db:
        current_app.logger.error("Error FATAL: No database connection in api_configuracion")
        return jsonify({"success": False, "message": "Error de conexión a Base de Datos"}), 500

    try:
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Evitar bloqueos indefinidos (5 segundos timeout)
        cursor.execute("SET statement_timeout = 5000") 
    except Exception as e:
        current_app.logger.error(f"Error creando cursor: {e}")
        return jsonify({"success": False, "message": "Error interno (Cursor)"}), 500

    if request.method == 'GET':
        try:
            cursor.execute("SELECT * FROM configuracion_sucursal WHERE sucursal_id = %s", (sucursal_id,))
            config = cursor.fetchone()
            
            if not config:
                config = {
                    "agenda_intervalo": "00:15:00",
                    "agenda_color_bloqueo": "#c7c7c7",
                    "agenda_color_habilitado": "#ffffff",
                    "agenda_color_reserva": "#6c63ff",
                    "agenda_color_completado": "#198754",
                    "app_fuente": "Inter"
                }
            
            # Asegurar string con formato HH:MM:SS (2 dígitos para hora)
            for field in ['agenda_intervalo', 'agenda_hora_inicio', 'agenda_hora_fin']:
                if field in config and config[field]:
                     val = config[field]
                     if isinstance(val, timedelta):
                         total_seconds = int(val.total_seconds())
                         hours = total_seconds // 3600
                         minutes = (total_seconds % 3600) // 60
                         seconds = total_seconds % 60
                         config[field] = f"{hours:02}:{minutes:02}:{seconds:02}"
                     else:
                         # Si ya es string, asegurarse formato HH:MM
                         config[field] = str(val)

            return jsonify({"success": True, "config": config})
        except Exception as e:
            current_app.logger.error(f"Error GET config QUERY: {e}")
            return jsonify({"success": False, "message": "Error al leer configuración"}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            current_app.logger.info(f"Datos recibidos para guardar: {data}")
            
            # Validar existencia previa
            cursor.execute("SELECT id FROM configuracion_sucursal WHERE sucursal_id = %s", (sucursal_id,))
            existe = cursor.fetchone()
            
            # Valores
            val_intervalo = data.get('agenda_intervalo', '00:15:00')
            val_bloqueo = data.get('agenda_color_bloqueo', '#c7c7c7')
            val_habilitado = data.get('agenda_color_habilitado', '#ffffff')
            val_reserva = data.get('agenda_color_reserva', '#6c63ff')
            val_completado = data.get('agenda_color_completado', '#198754')
            val_fuente = data.get('app_fuente', 'Inter')
            val_inicio = data.get('agenda_hora_inicio', '08:00')
            val_fin = data.get('agenda_hora_fin', '22:00')

            if existe:
                # UPDATE
                sql_update = """
                    UPDATE configuracion_sucursal SET
                        agenda_intervalo = %s,
                        agenda_color_bloqueo = %s,
                        agenda_color_habilitado = %s,
                        agenda_color_reserva = %s,
                        agenda_color_completado = %s,
                        app_fuente = %s,
                        agenda_hora_inicio = %s,
                        agenda_hora_fin = %s
                    WHERE sucursal_id = %s
                """
                cursor.execute(sql_update, (val_intervalo, val_bloqueo, val_habilitado, val_reserva, val_completado, val_fuente, val_inicio, val_fin, sucursal_id))
            else:
                # INSERT
                sql_insert = """
                    INSERT INTO configuracion_sucursal (
                        sucursal_id, agenda_intervalo, agenda_color_bloqueo, 
                        agenda_color_habilitado, agenda_color_reserva, agenda_color_completado, app_fuente,
                        agenda_hora_inicio, agenda_hora_fin
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql_insert, (sucursal_id, val_intervalo, val_bloqueo, val_habilitado, val_reserva, val_completado, val_fuente, val_inicio, val_fin))

            
            db.commit()
            current_app.logger.info("Configuración guardada exitosamente en DB.")
            return jsonify({"success": True, "message": "Configuración guardada correctamente."})
            
        except Exception as e:
            db.rollback()
            current_app.logger.error(f"Error POST config SAVE: {e}")
            return jsonify({"success": False, "message": f"Error al guardar: {str(e)}"}), 500

def timedelta_to_time_obj(obj):
    """
    Convierte inteligentemente el dato de horario a un objeto time.
    Maneja tanto si la BD devuelve timedelta como si devuelve time.
    """
    if obj is None: 
        return None
    
    # 🟢 CORRECCIÓN: Si ya es un objeto time, lo devolvemos tal cual
    if isinstance(obj, time):
        return obj
        
    # Si es un timedelta (duración), lo convertimos a hora
    if isinstance(obj, timedelta):
        total_seconds = int(obj.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return time(hours, minutes)
    
    return obj


# Asegúrate de importar esto al inicio de tu archivo routes.py
from app.services.whatsapp_service import enviar_alerta_reserva

# 🟢 1. IMPORTANTE: Agrega esta línea AL INICIO de tu archivo routes.py
# (Junto con los otros imports como datetime, jsonify, etc.)
from app.services.whatsapp_service import enviar_alerta_reserva

# ... (El resto de tus rutas) ...

@main_bp.route('/reservas/nueva', methods=['POST'])
@login_required
def nueva_reserva():
    """
    Crea una reserva y genera un Link de WhatsApp (Click-to-Chat)
    basado en plantillas de base de datos.
    """
    if not request.is_json:
        return jsonify({"success": False, "message": "Error: Se esperaba contenido JSON."}), 400
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Error: No se recibieron datos."}), 400

    db_conn = get_db()
    
    try:
        # --- 1. Recoger y Validar Datos ---
        errores = []
        
        sucursal_id = int(data.get('sucursal_id') or 0)
        cliente_id = int(data.get('cliente_id') or 0)
        empleado_id = int(data.get('empleado_id') or 0)
        servicio_id = int(data.get('servicio_id') or 0)
        fecha_hora_inicio_str = data.get('fecha_hora_inicio')
        notas_cliente = data.get('notas_cliente', '').strip() or None
        
        # Checkbox del usuario (True/False)
        enviar_whatsapp_flag = data.get('enviar_whatsapp', False)

        if not sucursal_id: errores.append("La sucursal es requerida.")
        if not cliente_id: errores.append("Debe seleccionar un cliente.")
        if not empleado_id: errores.append("Colaborador es obligatorio.")
        if not servicio_id: errores.append("Debe seleccionar un servicio.")
        
        # Validación de Zona Horaria (Perú)
        if not fecha_hora_inicio_str:
            errores.append('Falta la fecha y hora de inicio.')
        else:
            try:
                peru_tz = pytz.timezone('America/Lima')
                ahora_peru = datetime.now(peru_tz)
                fecha_hora_inicio = datetime.fromisoformat(fecha_hora_inicio_str)
                fecha_hora_inicio_aware = peru_tz.localize(fecha_hora_inicio)

                if fecha_hora_inicio_aware < ahora_peru:
                    errores.append('La fecha y hora de inicio no puede ser en el pasado.')
            except ValueError:
                errores.append('Formato de fecha y hora de inicio inválido.')

        if errores:
            return jsonify({"success": False, "errors": errores}), 400

        # --- 2. Validaciones de Negocio ---
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Obtener datos del servicio
            cursor.execute("SELECT duracion_minutos, precio, nombre FROM servicios WHERE id = %s AND activo = TRUE", (servicio_id,))
            servicio_seleccionado = cursor.fetchone()
            if not servicio_seleccionado:
                return jsonify({"success": False, "message": "Servicio no válido."}), 400
            
            duracion_servicio = timedelta(minutes=servicio_seleccionado['duracion_minutos'])
            fecha_hora_fin = fecha_hora_inicio + duracion_servicio
            precio_del_servicio = servicio_seleccionado['precio']
            nombre_servicio_str = servicio_seleccionado['nombre'] 

            # Validar Horarios
            dia_semana_reserva = fecha_hora_inicio.isoweekday()
            
            # 1. Turnos Recurrentes
            cursor.execute("SELECT hora_inicio, hora_fin FROM horarios_empleado WHERE empleado_id = %s AND dia_semana = %s", (empleado_id, dia_semana_reserva))
            turnos_recurrentes = cursor.fetchall()
            
            # 2. Turnos Extra (Específicos para la fecha)
            fecha_solo_dia = fecha_hora_inicio.date()
            cursor.execute("SELECT hora_inicio, hora_fin FROM horarios_extra WHERE empleado_id = %s AND fecha = %s", (empleado_id, fecha_solo_dia))
            turnos_extra = cursor.fetchall()

            # Combinar ambos
            turnos_del_dia = turnos_recurrentes + turnos_extra
            
            if not turnos_del_dia:
                return jsonify({"success": False, "message": f"El colaborador no trabaja el día seleccionado."}), 409
            
            esta_en_turno_valido = False
            for turno in turnos_del_dia:
                try:
                    # Intento robusto de conversión de hora
                    t_in = turno['hora_inicio'] if isinstance(turno['hora_inicio'], (datetime, type(datetime.now().time()))) else datetime.strptime(str(turno['hora_inicio']), "%H:%M:%S").time()
                    t_out = turno['hora_fin'] if isinstance(turno['hora_fin'], (datetime, type(datetime.now().time()))) else datetime.strptime(str(turno['hora_fin']), "%H:%M:%S").time()
                except:
                    t_in = turno['hora_inicio']
                    t_out = turno['hora_fin']

                if fecha_hora_inicio.time() >= t_in and fecha_hora_fin.time() <= t_out:
                    esta_en_turno_valido = True
                    break
            
            if not esta_en_turno_valido:
                return jsonify({"success": False, "message": "Fuera de horario laboral del colaborador."}), 409

            # Validar Ausencias y Choques (Resumido)
            cursor.execute("SELECT id FROM ausencias_empleado WHERE empleado_id=%s AND aprobado=TRUE AND fecha_hora_inicio<%s AND fecha_hora_fin>%s", (empleado_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone(): return jsonify({"success": False, "message": "Colaborador ausente."}), 409

            cursor.execute("SELECT id FROM reservas WHERE empleado_id=%s AND sucursal_id=%s AND estado NOT IN ('Cancelada', 'Cancelada por Cliente', 'Cancelada por Staff', 'No Asistio', 'Completada') AND fecha_hora_inicio<%s AND fecha_hora_fin>%s", (empleado_id, sucursal_id, fecha_hora_fin, fecha_hora_inicio))
            if cursor.fetchone(): return jsonify({"success": False, "message": "Horario ocupado."}), 409
            
            # --- 3. Insertar Reserva ---
            sql = "INSERT INTO reservas (sucursal_id, cliente_id, empleado_id, servicio_id, fecha_hora_inicio, fecha_hora_fin, estado, notas_cliente, precio_cobrado) VALUES (%s, %s, %s, %s, %s, %s, 'Programada', %s, %s) RETURNING id"
            val = (sucursal_id, cliente_id, empleado_id, servicio_id, fecha_hora_inicio, fecha_hora_fin, notas_cliente, precio_del_servicio)
            
            cursor.execute(sql, val)
            
            # --- 4. 🟢 GENERAR LINK DE WHATSAPP ---
            whatsapp_url = None
            
            if enviar_whatsapp_flag:
                # A. Obtener datos Cliente y Staff
                cursor.execute("SELECT razon_social_nombres, telefono FROM clientes WHERE id = %s", (cliente_id,))
                c_data = cursor.fetchone()
                
                cursor.execute("SELECT nombres FROM empleados WHERE id = %s", (empleado_id,))
                e_data = cursor.fetchone()
                
                # B. Obtener Plantilla de la BD
                # Asegúrate de haber creado la tabla 'plantillas_whatsapp' y el registro 'reserva_nueva'
                cursor.execute("SELECT contenido FROM plantillas_whatsapp WHERE tipo = 'reserva_nueva'")
                tpl_row = cursor.fetchone()
                
                # C. Construir el Link
                if c_data and c_data['telefono'] and tpl_row:
                    try:
                        plantilla_raw = tpl_row['contenido']
                        plantilla_limpia = plantilla_raw.replace('%0A', '\n').replace('\\n', '\n')
                        
                        # Formatear mensaje reemplazando variables
                        mensaje_base = plantilla_limpia.format(
                            cliente=c_data['razon_social_nombres'],
                            fecha=fecha_hora_inicio.strftime('%d/%m/%Y'),
                            hora=fecha_hora_inicio.strftime('%I:%M %p'),
                            servicio=nombre_servicio_str,
                            staff=e_data['nombres']
                        )
                        
                        # Agregar Footer con Redes
                        mensaje_final = (
                            f"{mensaje_base}\n\n"
                            f"Síguenos en nuestras redes:\n"
                            f"👍 Facebook: https://www.facebook.com/BarberiaAbancay\n"
                            f"🎵 TikTok: https://www.tiktok.com/@jvbarberia\n"
                            f"📸 Instagram: https://www.instagram.com/jvstudio_formen/\n"
                            f"📞 WhatsApp: 965 432 443"
                        )
                        
                        # Preparar teléfono (Asegurar prefijo 51 Perú)
                        telefono = str(c_data['telefono']).strip().replace(' ', '')
                        if len(telefono) == 9: 
                            telefono = f"51{telefono}"
                        
                        # Codificar URL (convertir espacios a %20, etc.)
                        whatsapp_url = f"whatsapp://send?phone={telefono}&text={quote(mensaje_final)}"
                        
                    except Exception as e_link:
                        print(f"Error generando link: {e_link}")

            db_conn.commit()
            
            # D. Retornar URL al JavaScript
            return jsonify({
                "success": True, 
                "message": f'Reserva creada exitosamente.',
                "whatsapp_url": whatsapp_url 
            }), 201

    except Exception as e:
        if db_conn:
            db_conn.rollback()
        current_app.logger.error(f"Error procesando nueva reserva: {e}")
        return jsonify({"success": False, "message": f"Error interno: {str(e)}"}), 500
       
            
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

        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

    except Exception as err:
        if db_conn:
            db_conn.rollback()
        current_app.logger.error(f"Error DB en api_marcar_reserva_completada (Reserva ID: {reserva_id}): {err}")
        return jsonify({"success": False, "message": "Error interno del servidor al actualizar la reserva.", "detalle": str(err)}), 500
    finally:
        if cursor:
            cursor.close()
        if 'cursor_update' in locals() and cursor_update:
            cursor_update.close()

# --- FUNCIONES AUXILIARES PARA MENSAJERÍA ---

def _generar_link_gcal_interno(titulo, inicio_dt, fin_dt, detalles, ubicacion):
    """
    Genera un enlace para agregar evento a Google Calendar.
    Formato: https://calendar.google.com/calendar/render?action=TEMPLATE&text=...
    """
    try:
        base_url = "https://calendar.google.com/calendar/render?action=TEMPLATE"
        # Google Calendar usa formato YYYYMMDDTHHMMSSZ (UTC) o local sin Z
        # Usaremos local time string: YYYYMMDDTHHMMSS
        fmt = "%Y%m%dT%H%M%S"
        
        # Asumiendo que inicio_dt y fin_dt ya son objetos datetime
        fechas = f"{inicio_dt.strftime(fmt)}/{fin_dt.strftime(fmt)}"
        
        from urllib.parse import quote
        
        params = [
            f"text={quote(titulo)}",
            f"dates={fechas}",
            f"details={quote(detalles)}",
            f"location={quote(ubicacion)}",
            "sf=true", # Source format
            "output=xml"
        ]
        
        return f"{base_url}&{'&'.join(params)}"
    except Exception as e:
        print(f"Error generando link calendar: {e}")
        return ""

@main_bp.route('/api/reservas/<int:reserva_id>/whatsapp-link')
@login_required
def api_generar_link_whatsapp_reserva(reserva_id):
    """
    Genera el enlace de WhatsApp dinámico para RECORDATORIO o AVISO STAFF.
    Incluye integración con Google Calendar para el Staff.
    """
    tipo = request.args.get('tipo', 'recordatorio') # 'recordatorio' | 'aviso_staff'
    db = get_db()
    
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Obtener datos completos
            sql = """
                SELECT r.*, 
                       c.razon_social_nombres as cliente_nombre, c.telefono as cliente_tel,
                       e.nombres as staff_nombre, e.telefono as staff_tel,
                       s.nombre as servicio_nombre, s.duracion_minutos
                FROM reservas r
                LEFT JOIN clientes c ON r.cliente_id = c.id
                LEFT JOIN empleados e ON r.empleado_id = e.id
                LEFT JOIN servicios s ON r.servicio_id = s.id
                WHERE r.id = %s
            """
            cursor.execute(sql, (reserva_id,))
            reserva = cursor.fetchone()
            
            if not reserva:
                return jsonify({"success": False, "message": "Reserva no encontrada."})
            
            # 2. Generar Link
            phone_target = ""
            mensaje = ""
            
            # Objetos datetime
            inicio = reserva['fecha_hora_inicio'] 
            fin = reserva['fecha_hora_fin']
            
            # A. Lógica RECORDATORIO CLIENTE
            if tipo == 'recordatorio':
                phone_target = reserva['cliente_tel']
                if not phone_target:
                    return jsonify({"success": False, "message": "El cliente no tiene teléfono registrado."})
                
                # Plantilla
                mensaje = (
                    f"Hola {reserva['cliente_nombre']}! 👋\n"
                    f"Te recordamos tu cita en *JV Studio*:\n\n"
                    f"🗓️ Fecha: {inicio.strftime('%d/%m/%Y')}\n"
                    f"⏰ Hora: {inicio.strftime('%I:%M %p')}\n"
                    f"💇 Servicio: {reserva['servicio_nombre']}\n"
                    f"📍 Staff: {reserva['staff_nombre'] or 'Por asignar'}\n\n"
                    f"¡Nos vemos pronto!"
                )

            # B. Lógica AVISO STAFF (Con Google Calendar)
            elif tipo == 'aviso_staff':
                phone_target = reserva['staff_tel']
                if not phone_target:
                    return jsonify({"success": False, "message": "El colaborador no tiene teléfono registrado."})
                
                # Generar Link Calendar
                gcal_link = _generar_link_gcal_interno(
                    titulo=f"Cita: {reserva['cliente_nombre']} - {reserva['servicio_nombre']}",
                    inicio_dt=inicio,
                    fin_dt=fin,
                    detalles=f"Cliente: {reserva['cliente_nombre']}\nServicio: {reserva['servicio_nombre']}\nNotas: {reserva['notas_cliente'] or ''}",
                    ubicacion="JV Studio, Jr. Andahuaylas 216"
                )
                
                mensaje = (
                    f"🔔 *NUEVA ASIGNACION*\n"
                    f"Has sido asignado a una cita:\n\n"
                    f"👤 Cliente: {reserva['cliente_nombre']}\n"
                    f"⏰ Hora: {inicio.strftime('%I:%M %p')}\n"
                    f"✂️ Servicio: {reserva['servicio_nombre']}\n\n"
                    f"📅 *Agregar a tu Calendario:* \n{gcal_link}" 
                )
            
            # 3. Formatear Teléfono y URL
            from urllib.parse import quote
            
            phone_clean = ''.join(filter(str.isdigit, str(phone_target)))
            if len(phone_clean) == 9: phone_clean = '51' + phone_clean # Prefijo Perú
            
            url = f"https://wa.me/{phone_clean}?text={quote(mensaje)}"
            
            return jsonify({"success": True, "url": url})
            
    except Exception as e:
        current_app.logger.error(f"Error generando whatsapp link: {e}")
        return jsonify({"success": False, "message": str(e)})


@main_bp.route('/api/reservas/<int:reserva_id>', methods=['GET'])
@login_required
def api_get_reserva_detalle(reserva_id):
    """
    Devuelve los detalles de una reserva específica en formato JSON.
    CORREGIDO: Incluye teléfonos y usa LEFT JOIN para staff 'Sin asignar'.
    """
    db_conn = get_db()
    cursor = None
    try:
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # 🟢 CAMBIOS IMPORTANTES EN EL SQL:
        # 1. Usamos LEFT JOIN para clientes, empleados y servicios (para que no falle si falta alguno).
        # 2. Agregamos c.telefono y e.telefono (CRUCIAL PARA WHATSAPP).
        # 3. Agregamos alias 'empleado_nombre' y 'staff' para que el JS lo encuentre fácil.
        
        sql = """
            SELECT 
                r.id, 
                r.fecha_hora_inicio, 
                r.fecha_hora_fin, 
                r.estado,
                r.notas_cliente,
                r.notas_internas,
                r.precio_cobrado,
                r.fecha_creacion,
                r.fecha_actualizacion,
                
                -- DATOS CLIENTE
                r.cliente_id,
                c.razon_social_nombres AS cliente_nombre_completo, -- O c.nombres dependiendo de tu tabla
                c.telefono AS tel_cliente,  -- <--- NECESARIO PARA EL BOTÓN RECORDAR
                
                -- DATOS EMPLEADO (STAFF)
                r.empleado_id,
                e.nombres AS empleado_nombre, -- <--- PARA QUE EL JS NO DE "UNDEFINED"
                e.nombres AS staff,           -- <--- ALIAS EXTRA
                CONCAT(e.nombres, ' ', e.apellidos) AS empleado_nombre_completo,
                e.telefono AS tel_staff,      -- <--- NECESARIO PARA EL BOTÓN AVISAR STAFF
                
                -- DATOS SERVICIO
                r.servicio_id,
                s.nombre AS servicio_nombre,
                s.duracion_minutos AS servicio_duracion_minutos,
                s.precio AS servicio_precio_base

            FROM reservas r
            LEFT JOIN clientes c ON r.cliente_id = c.id
            LEFT JOIN empleados e ON r.empleado_id = e.id
            LEFT JOIN servicios s ON r.servicio_id = s.id
            WHERE r.id = %s
        """
        cursor.execute(sql, (reserva_id,))
        reserva = cursor.fetchone()

        if reserva:
            # 🟢 CORRECCIÓN ROBUSTA PARA STAFF 'SIN ASIGNAR'
            # Si el ID existe pero el JOIN falló, o si el nombre es nulo
            if reserva['empleado_id'] and not reserva['empleado_nombre']:
                 # Intentamos buscarlo manualmente por si acaso (Integridad DB)
                 cursor.execute("SELECT nombres FROM empleados WHERE id = %s", (reserva['empleado_id'],))
                 emp_fallback = cursor.fetchone()
                 if emp_fallback:
                     reserva['empleado_nombre'] = emp_fallback['nombres']
                     reserva['staff'] = emp_fallback['nombres']
            
            # Formatear Fechas para JSON
            if reserva.get('fecha_hora_inicio'):
                reserva['fecha_hora_inicio'] = reserva['fecha_hora_inicio'].isoformat()
            if reserva.get('fecha_hora_fin'):
                reserva['fecha_hora_fin'] = reserva['fecha_hora_fin'].isoformat()
            if reserva.get('fecha_creacion'):
                reserva['fecha_creacion'] = reserva['fecha_creacion'].isoformat()
            if reserva.get('fecha_actualizacion'):
                reserva['fecha_actualizacion'] = reserva['fecha_actualizacion'].isoformat()
            
            
            
            # Formatear Fechas para JSON
            
            return jsonify(reserva), 200
        else:
            return jsonify({"error": "Reserva no encontrada"}), 404

    except Exception as err:
        current_app.logger.error(f"Error DB en api_get_reserva_detalle (Reserva ID: {reserva_id}): {err}")
        return jsonify({"error": "Error interno", "detalle": str(err)}), 500
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
# @admin_required  <-- Actívalo si ya tienes el decorador funcionando
def gestionar_horarios_empleado(empleado_id):
    db_conn = get_db()
    cursor_empleado = None
    cursor_horarios = None
    empleado = None 
    # Inicializar diccionario para los 7 días (claves 1 al 7)
    horarios_por_dia = {dia_num: [] for dia_num in range(1, 8)} 

    try:
        # 1. Obtener Empleado
        cursor_empleado = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_empleado.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_empleado.fetchone()

        if not empleado:
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        # 2. Obtener Horarios (CORREGIDO PARA POSTGRESQL)
        cursor_horarios = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # --- CAMBIO IMPORTANTE AQUÍ ---
        # MySQL: TIME_FORMAT(hora_inicio, '%H:%i')
        # Postgres: TO_CHAR(hora_inicio, 'HH24:MI')
        sql_horarios = """
            SELECT id, dia_semana, 
                   TO_CHAR(hora_inicio, 'HH24:MI') AS hora_inicio_f, 
                   TO_CHAR(hora_fin, 'HH24:MI') AS hora_fin_f 
            FROM horarios_empleado 
            WHERE empleado_id = %s 
            ORDER BY dia_semana, hora_inicio
        """
        cursor_horarios.execute(sql_horarios, (empleado_id,))
        horarios_existentes_raw = cursor_horarios.fetchall()
        
        for horario in horarios_existentes_raw:
            # Accedemos por nombre de columna (gracias a RealDictCursor)
            dia = horario['dia_semana']
            if dia in horarios_por_dia:
                horarios_por_dia[dia].append(horario)

    except Exception as err:
        flash(f"Error al cargar datos de horarios: {err}", "danger")
        current_app.logger.error(f"Error DB en gestionar_horarios_empleado (Empleado ID: {empleado_id}): {err}")
    finally:
        if cursor_empleado: cursor_empleado.close()
        if cursor_horarios: cursor_horarios.close()

    if not empleado: 
        return redirect(url_for('main.listar_empleados'))
        
    # Mapa de días estático por si la función externa falla
    dias_semana_map = {1: 'Lunes', 2: 'Martes', 3: 'Miércoles', 4: 'Jueves', 5: 'Viernes', 6: 'Sábado', 7: 'Domingo'}
    
    # Aseguramos que la función de opciones de tiempo exista
    try:
        opciones_tiempo = generar_opciones_tiempo_15min()
    except NameError:
        # Si no tienes importada la función, usa esta lista básica o impórtala arriba
        opciones_tiempo = [] 
    
    return render_template('empleados/gestionar_horarios.html', 
                           empleado=empleado, 
                           horarios_por_dia=horarios_por_dia, 
                           dias_semana_map=dias_semana_map,
                           opciones_tiempo=opciones_tiempo)


@main_bp.route('/empleados/<int:empleado_id>/horarios/agregar_turno', methods=['POST'])
@login_required
@admin_required
def agregar_turno_horario(empleado_id):
    db_conn = get_db()
    
    # 1. Validar empleado
    cursor_check = None
    try:
        cursor_check = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_check.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cursor_check.fetchone():
            flash(f"Empleado no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))
    except Exception as e:
        flash(f"Error verificando empleado: {e}", "danger")
        return redirect(url_for('main.listar_empleados'))
    finally:
        if cursor_check: cursor_check.close()

    # 2. Obtener datos del formulario
    try:
        dia_semana = int(request.form.get('dia_semana'))
        hora_inicio_str = request.form.get('hora_inicio')
        hora_fin_str = request.form.get('hora_fin')
    except (ValueError, TypeError):
        flash("Datos de formulario inválidos.", "warning")
        return redirect(url_for('main.gestionar_horarios_empleado', empleado_id=empleado_id))

    errores = []
    if dia_semana not in range(1, 8): errores.append("Día inválido.")
    if not hora_inicio_str or not hora_fin_str: errores.append("Horas obligatorias.")

    # 3. Convertir a objetos time
    nuevo_inicio = None
    nuevo_fin = None
    if not errores:
        try:
            nuevo_inicio = datetime.strptime(hora_inicio_str, '%H:%M').time()
            nuevo_fin = datetime.strptime(hora_fin_str, '%H:%M').time()
            if nuevo_fin <= nuevo_inicio:
                errores.append("La hora fin debe ser mayor a la de inicio.")
        except ValueError:
            errores.append("Formato de hora inválido.")

    # 4. Validar Solapamiento (Lógica simplificada para Postgres)
    if not errores:
        cursor_solap = None
        try:
            cursor_solap = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Postgres devuelve objetos datetime.time directamente, no timedelta
            cursor_solap.execute("""
                SELECT hora_inicio, hora_fin 
                FROM horarios_empleado 
                WHERE empleado_id = %s AND dia_semana = %s
            """, (empleado_id, dia_semana))
            turnos_existentes = cursor_solap.fetchall()

            for turno in turnos_existentes:
                ex_inicio = turno['hora_inicio'] # Ya es objeto time
                ex_fin = turno['hora_fin']       # Ya es objeto time
                
                # Lógica de solapamiento: (NuevoInicio < ViejoFin) AND (NuevoFin > ViejoInicio)
                if (nuevo_inicio < ex_fin) and (nuevo_fin > ex_inicio):
                    errores.append(f"Se solapa con el turno: {ex_inicio.strftime('%H:%M')} - {ex_fin.strftime('%H:%M')}")
                    break
                    
        except Exception as e:
            current_app.logger.error(f"Error solapamiento: {e}")
            errores.append(f"Error al verificar horarios: {e}")
        finally:
            if cursor_solap: cursor_solap.close()

    # 5. Insertar o mostrar errores
    if errores:
        for err in errores: flash(err, 'warning')
    else:
        cursor_insert = None
        try:
            cursor_insert = db_conn.cursor()
            sql = "INSERT INTO horarios_empleado (empleado_id, dia_semana, hora_inicio, hora_fin) VALUES (%s, %s, %s, %s)"
            cursor_insert.execute(sql, (empleado_id, dia_semana, hora_inicio_str, hora_fin_str))
            db_conn.commit()
            flash("Turno agregado correctamente.", "success")
        except Exception as e:
            db_conn.rollback()
            flash(f"Error al guardar: {e}", "danger")
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
        cursor_find = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM horarios_empleado WHERE id = %s", (horario_id,))
        turno_actual = cursor.fetchone()
        if turno_actual:
            # Convertir TIME de BD (timedelta) a objetos time de Python para el formulario
            turno_actual['hora_inicio_obj'] = timedelta_to_time(turno_actual['hora_inicio'])
            turno_actual['hora_fin_obj'] = timedelta_to_time(turno_actual['hora_fin'])
    except Exception as err:
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
        cursor_emp = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # CORRECCIÓN AQUÍ: Añadir 'id' a la consulta SELECT
        cursor_emp.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_emp.fetchone()
    except Exception as err_emp:
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
                cursor_solap = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
            except Exception as err_sol:
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
            except Exception as err_upd:
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
        cursor_empleado = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_empleado.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id,))
        empleado = cursor_empleado.fetchone()

        if not empleado:
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))

        cursor_ausencias = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # CORRECCIÓN EN LA SIGUIENTE CONSULTA SQL:
        sql_ausencias = """
            SELECT id, 
                   TO_CHAR(fecha_hora_inicio, 'DD/MM/YYYY') AS inicio_f,
                   TO_CHAR(fecha_hora_fin, 'DD/MM/YYYY') AS fin_f,
                   fecha_hora_inicio, fecha_hora_fin, -- Mantenemos las originales para lógica futura (ej. editar)
                   tipo_ausencia, descripcion, aprobado
            FROM ausencias_empleado 
            WHERE empleado_id = %s 
            ORDER BY fecha_hora_inicio DESC
        """
        cursor_ausencias.execute(sql_ausencias, (empleado_id,))
        ausencias_empleado = cursor_ausencias.fetchall()

    except Exception as err:
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
        cursor_check_empleado = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_check_empleado.execute("SELECT id FROM empleados WHERE id = %s", (empleado_id,))
        if not cursor_check_empleado.fetchone():
            flash(f"Empleado con ID {empleado_id} no encontrado.", "warning")
            return redirect(url_for('main.listar_empleados'))
    except Exception as err_check:
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
            cursor_solapamiento = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor_solapamiento.execute("""
                SELECT id FROM ausencias_empleado 
                WHERE empleado_id = %s 
                AND (
                    (%s < fecha_hora_fin AND %s > fecha_hora_inicio)
                )
            """, (empleado_id, fecha_hora_inicio, fecha_hora_fin)) # Parámetros para la consulta
            
            if cursor_solapamiento.fetchone():
                errores.append("El período de ausencia se solapa con otra ausencia existente para este empleado.")
        except Exception as err_solap:
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
        except Exception as err_insert:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Necesitamos empleado_id para redirigir y para el título/contexto
        cursor.execute("SELECT * FROM ausencias_empleado WHERE id = %s", (ausencia_id,))
        ausencia_actual = cursor.fetchone()
    except Exception as err:
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
        cursor_emp = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor_emp.execute("SELECT id, nombres, apellidos FROM empleados WHERE id = %s", (empleado_id_actual,))
        empleado = cursor_emp.fetchone()
    except Exception as err_emp:
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
                cursor_solap = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
            except Exception as err_solap:
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
            except Exception as err_upd:
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
        cursor_find = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

    except Exception as err:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_productos ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_productos WHERE id = %s", (categoria_id,))
        categoria_actual = cursor.fetchone()
    except Exception as err:
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
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM categorias_productos WHERE nombre = %s AND id != %s", (nombre_nuevo, categoria_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra categoría de producto con el nombre "{nombre_nuevo}".')
            except Exception as err_check_nombre:
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
            except Exception as err_upd:
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
        # cursor_check = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
            
    except Exception as err:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
            
        except (ValueError, Exception) as e:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM categorias_productos WHERE activo = TRUE ORDER BY nombre")
            categorias_prod = cursor.fetchall()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM marcas WHERE activo = TRUE ORDER BY nombre")
            marcas_todas = cursor.fetchall()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre_empresa FROM proveedores WHERE activo = TRUE ORDER BY nombre_empresa")
            proveedores_todos = cursor.fetchall()
    except Exception as e:
        flash(f"Error al cargar datos del formulario: {e}", "danger")

    # Obtener el producto actual que se está editando
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
                with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

        except (ValueError, Exception) as e:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion, activo FROM marcas ORDER BY nombre")
        lista_de_marcas = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion, activo FROM marcas WHERE id = %s", (marca_id,))
        marca_actual = cursor.fetchone()
    except Exception as err:
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
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM marcas WHERE nombre = %s AND id != %s", (nombre_nuevo, marca_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra marca con el nombre "{nombre_nuevo}".')
            except Exception as err_check_nombre:
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
            except Exception as err_upd:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT id, nombre_empresa, ruc, nombre_contacto, telefono, email, activo 
            FROM proveedores 
            ORDER BY nombre_empresa
        """)
        lista_de_proveedores = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM proveedores WHERE id = %s", (proveedor_id,))
        proveedor_actual = cursor.fetchone()
    except Exception as err:
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
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM proveedores WHERE nombre_empresa = %s AND id != %s", (nombre_empresa_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el nombre "{nombre_empresa_nuevo}".')
            except Exception as err_check: current_app.logger.error(f"Error DB verificando nombre_empresa: {err_check}")
            finally: 
                if cursor: cursor.close(); cursor = None

        if ruc_db_nuevo and ruc_db_nuevo != proveedor_actual.get('ruc'):
            try:
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM proveedores WHERE ruc = %s AND id != %s", (ruc_db_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el RUC "{ruc_db_nuevo}".')
            except Exception as err_check: current_app.logger.error(f"Error DB verificando RUC: {err_check}")
            finally: 
                if cursor: cursor.close(); cursor = None
        
        if email_db_nuevo and email_db_nuevo.lower() != (proveedor_actual.get('email', '') or '').lower():
            try:
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM proveedores WHERE email = %s AND id != %s", (email_db_nuevo, proveedor_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe un proveedor con el email "{email_db_nuevo}".')
            except Exception as err_check: current_app.logger.error(f"Error DB verificando email: {err_check}")
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
            except Exception as err_upd:
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
        cursor_read = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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


# --- RUTAS PARA VENTAS ---


import json # Asegúrate de tener esto arriba


@main_bp.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    db_conn = get_db()
    sucursal_id = session.get('sucursal_id')
    
    if not sucursal_id:
        flash("Seleccione una sucursal para continuar.", "warning")
        return redirect(url_for('main.index'))

    # ==============================================================================
    # --- VALIDACIÓN DE CAJA ABIERTA ---
    # ==============================================================================
    try:
        with db_conn.cursor() as cursor_val:
            cursor_val.execute("""
                SELECT id FROM caja_sesiones 
                WHERE usuario_id = %s AND sucursal_id = %s AND estado = 'Abierta'
            """, (current_user.id, sucursal_id))
            caja_abierta = cursor_val.fetchone()

            if not caja_abierta:
                flash("⛔ ACCESO DENEGADO: Debes ABRIR CAJA antes de realizar ventas.", "danger")
                return redirect(url_for('main.index')) 
    except Exception as e:
        flash(f"Error verificando caja: {e}", "danger")
        return redirect(url_for('main.index'))
    
    # --- LÓGICA POST (PROCESAR VENTA) ---
    if request.method == 'POST':
        cursor = None
        try:
            # 1. Recoger Datos
            cliente_id_str = request.form.get('cliente_id')
            empleado_id = request.form.get('empleado_id')
            tipo_comprobante = request.form.get('tipo_comprobante')

            cliente_receptor_id = int(cliente_id_str) if cliente_id_str and cliente_id_str.strip() else None
            cliente_id = cliente_receptor_id  # Alias para compatibilidad con bloques inferiores
            empleado_id = int(empleado_id) if empleado_id and empleado_id.strip() else None

            
            items_json = request.form.get('items_lista')
            pagos_json = request.form.get('pagos_lista')
            
            items = json.loads(items_json) if items_json else []
            pagos = json.loads(pagos_json) if pagos_json else []
            
            if not items: 
                raise ValueError("No se puede registrar una venta sin productos o servicios.")

            if not empleado_id:
                raise ValueError("Debe seleccionar un Colaborador responsable de la venta.")

            descuento_global = float(request.form.get('descuento_global', 0) or 0)
            campana_id = request.form.get('campana_id') or None
            
            # 2. Calcular Totales y Validar Cliente
            subtotal_servicios = sum(float(item['precio']) * float(item['cantidad']) for item in items if item['tipo'] == 'servicio')
            subtotal_productos = sum(float(item['precio']) * float(item['cantidad']) for item in items if item['tipo'] == 'producto')
            
            monto_total_bruto = subtotal_servicios + subtotal_productos
            monto_final = monto_total_bruto - descuento_global

            cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            if tipo_comprobante == 'Factura Electrónica':
                if not cliente_receptor_id:
                    raise ValueError("Se requiere un cliente para la Factura Electrónica.")
                cursor.execute("SELECT numero_documento FROM clientes WHERE id = %s", (cliente_receptor_id,))
                cliente_doc = cursor.fetchone()
                if not cliente_doc or len(cliente_doc['numero_documento']) != 11:
                    raise ValueError("El cliente debe tener un RUC de 11 dígitos para Factura Electrónica.")

            # 3. Obtener Serie y Número
            cursor.execute("""
                SELECT serie, ultimo_numero 
                FROM series_comprobantes 
                WHERE sucursal_id = %s AND tipo_comprobante = %s AND activo = TRUE
                ORDER BY serie DESC LIMIT 1
            """, (sucursal_id, tipo_comprobante))
            serie_row = cursor.fetchone()
            
            if not serie_row:
                raise ValueError(f"No hay una serie activa configurada para '{tipo_comprobante}' en esta sucursal.")

            serie_comprobante = serie_row['serie']
            nuevo_numero = serie_row['ultimo_numero'] + 1
            numero_comprobante_str = str(nuevo_numero).zfill(8)

            cursor.execute("""
                UPDATE series_comprobantes SET ultimo_numero = %s 
                WHERE sucursal_id = %s AND serie = %s
            """, (nuevo_numero, sucursal_id, serie_comprobante))

            # 4. Vincular con Caja Abierta
            cursor.execute("SELECT id FROM caja_sesiones WHERE usuario_id=%s AND estado='Abierta' AND sucursal_id=%s", (current_user.id, sucursal_id))
            row_caja = cursor.fetchone()
            caja_id = row_caja['id'] if row_caja else None

            # 5. Insertar Venta
            sql_venta = """
                INSERT INTO ventas (
                    sucursal_id, cliente_receptor_id, empleado_id, fecha_venta, 
                    tipo_comprobante, serie_comprobante, numero_comprobante,
                    subtotal_servicios, subtotal_productos, descuento_monto, monto_final_venta,
                    estado_pago, campana_id, caja_sesion_id
                ) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s, 'Pagado', %s, %s) RETURNING id """
            
            cursor.execute(sql_venta, (
                sucursal_id, cliente_receptor_id, empleado_id, tipo_comprobante, 
                serie_comprobante, numero_comprobante_str, subtotal_servicios, 
                subtotal_productos, descuento_global, monto_final, campana_id, caja_id
            ))
            venta_id = cursor.fetchone()['id']

            # 6. Insertar Ítems y Actualizar Stock
            
            # (Se eliminó la lógica de % Comisión de Empleado - Ahora es por Producto Fijo)

            sql_item = """
                INSERT INTO venta_items (venta_id, servicio_id, producto_id, descripcion_item_venta, cantidad, precio_unitario_venta, subtotal_item_bruto, subtotal_item_neto, es_hora_extra, porcentaje_servicio_extra, comision_servicio_extra, entregado_al_colaborador) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
                RETURNING id
            """
            
            total_fidelidad = 0.0 # Acumulador para cubrir con Gasto
            
            for item in items:
                total_item = float(item['precio']) * float(item['cantidad'])
                
                # Detectar Fidelidad
                desc_fid = 0.0
                if item.get('loyalty_applied') and item.get('loyalty_pct'):
                    pct_fid = float(item['loyalty_pct'])
                    desc_fid = total_item * (pct_fid / 100.0)
                    total_fidelidad += desc_fid
                
                # Cálculo de Comisión Extra (Solo Servicios)
                es_extra = item.get('es_hora_extra', False)
                pct_extra = float(item.get('porcentaje_servicio_extra', 0)) if es_extra else 0.00
                comision_extra = 0.00
                
                if es_extra and pct_extra > 0:
                    comision_extra = total_item * (pct_extra / 100.0)

                cursor.execute(sql_item, (
                    venta_id, 
                    item['id'] if item['tipo'] == 'servicio' else None,
                    item['id'] if item['tipo'] == 'producto' else None,
                    item['descripcion'], item['cantidad'], item['precio'], 
                    total_item, total_item,
                    es_extra,
                    pct_extra,
                    comision_extra
                ))
                venta_item_id = cursor.fetchone()['id']

                if item['tipo'] == 'producto':
                    # A. OBTENER DATOS DEL PRODUCTO (Stock y Comisión)
                    cursor.execute("SELECT stock_actual, comision_vendedor_monto FROM productos WHERE id = %s", (item['id'],))
                    res_prod = cursor.fetchone()
                    
                    if res_prod:
                        stock_anterior = res_prod['stock_actual']
                        comision_unitaria = float(res_prod.get('comision_vendedor_monto') or 0.00)
                        
                        # B. GENERAR COMISIÓN (Si existe monto)
                        if comision_unitaria > 0:
                            total_comision_prod = comision_unitaria * float(item['cantidad'])
                            cursor.execute("""
                                INSERT INTO comisiones (venta_item_id, empleado_id, monto_comision, porcentaje, fecha_generacion, estado)
                                VALUES (%s, %s, %s, 0.00, CURRENT_TIMESTAMP, 'Pendiente')
                            """, (venta_item_id, empleado_id, total_comision_prod))

                        # C. ACTUALIZAR KARDEX (Stock)
                        cantidad_salida = float(item['cantidad'])
                        nuevo_stock = stock_anterior - cantidad_salida

                    cursor.execute("UPDATE productos SET stock_actual = %s WHERE id = %s", (nuevo_stock, item['id']))

                    cursor.execute("""
                        INSERT INTO kardex (producto_id, tipo_movimiento, cantidad, stock_anterior, stock_actual, motivo, usuario_id, venta_id)
                        VALUES (%s, 'VENTA', %s, %s, %s, %s, %s, %s)
                    """, (item['id'], -cantidad_salida, stock_anterior, nuevo_stock, f"Venta {serie_comprobante}-{numero_comprobante_str}", current_user.id, venta_id))
                    
            # 7. Insertar Pagos
            if not pagos:
                pagos = [{'metodo': 'Efectivo', 'monto': monto_final, 'referencia': ''}]
            sql_pago = "INSERT INTO venta_pagos (venta_id, metodo_pago, monto, referencia_pago) VALUES (%s, %s, %s, %s)"
            for p in pagos:
                cursor.execute(sql_pago, (venta_id, p['metodo'], p['monto'], p.get('referencia')))

            # 8. PROPINA
            monto_propina = request.form.get('monto_propina')
            empleado_propina_id = request.form.get('empleado_propina_id')
            metodo_propina = request.form.get('metodo_propina')

            if monto_propina and empleado_propina_id:
                try:
                    monto_p_float = float(monto_propina)
                    if monto_p_float > 0:
                        cursor.execute("""
                            INSERT INTO propinas (empleado_id, monto, metodo_pago, fecha_registro, entregado_al_barbero, venta_asociada_id, registrado_por)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP, FALSE, %s, %s)
                        """, (empleado_propina_id, monto_p_float, metodo_propina, venta_id, current_user.id))

                        cursor.execute("""
                            INSERT INTO movimientos_caja (tipo, monto, concepto, metodo_pago, usuario_id)
                            VALUES ('INGRESO', %s, %s, %s, %s)
                        """, (monto_p_float, f"Propina Venta #{serie_comprobante}-{numero_comprobante_str}", metodo_propina, current_user.id))
                except ValueError: pass

            # 9. (NUEVO) REGISTRAR GASTO POR FIDELIDAD Y CONSUMIR ITEMS
            if total_fidelidad > 0:
                # A. Registrar Gasto
                cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Descuento Fidelidad'")
                cat = cursor.fetchone()
                cat_id = cat['id'] if cat else None
                
                if not cat_id:
                     cursor.execute("INSERT INTO categorias_gastos (nombre, descripcion) VALUES ('Descuento Fidelidad', 'Automático por sistema') RETURNING id")
                     cat_id = cursor.fetchone()['id']

                # Insertar Gasto (Usando esquema correcto)
                cursor.execute("""
                    INSERT INTO gastos (sucursal_id, categoria_gasto_id, caja_sesion_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id)
                    VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, 'Interno', %s)
                """, (sucursal_id, cat_id, caja_id, f"Cobertura Fidelidad Venta #{serie_comprobante}-{numero_comprobante_str}", total_fidelidad, current_user.id))

                # Movimiento de Caja (Reflejando la salida de dinero virtual para cuadrar)
                cursor.execute("""
                    INSERT INTO movimientos_caja (tipo, monto, concepto, metodo_pago, usuario_id, caja_sesion_id)
                    VALUES ('EGRESO', %s, %s, 'SISTEMA', %s, %s)
                """, (total_fidelidad, f"Cobertura Fidelidad #{serie_comprobante}-{numero_comprobante_str}", current_user.id, caja_id))

                # B. Consumir Items (Anti-Double-Dip)
                from .routes_marketing import consumir_items_fidelidad
                
                for idx, item in enumerate(items):
                    if item.get('loyalty_applied') and item.get('loyalty_rule_id'):
                        rule_id = item['loyalty_rule_id']
                        group_id = f"SALE_{venta_id}_ITEM_{idx}"
                        consumir_items_fidelidad(cliente_id, rule_id, group_id)

            # 9.5 (NUEVO) CANJE DE PUNTOS
            puntos_canjeados = int(request.form.get('puntos_canjeados') or 0)
            if puntos_canjeados > 0 and cliente_id:
                # 1. Validar Saldo (Doble chequeo)
                cursor.execute("SELECT puntos_fidelidad FROM clientes WHERE id = %s", (cliente_id,))
                row_pts = cursor.fetchone()
                saldo_actual = row_pts['puntos_fidelidad'] if row_pts else 0
                
                if saldo_actual >= puntos_canjeados:
                    # 2. Calcular descuento (25 pts = 1 sol)
                    monto_desc_puntos = puntos_canjeados / 25.0
                    
                    # 3. Determinar el Método de Gasto según el pago de la venta
                    # Si al menos un pago es Efectivo, el canje se considera salida de Efectivo para cuadre
                    # Si todo es digital, el canje es Interno.
                    es_pago_efectivo = any(p.get('metodo') == 'Efectivo' for p in pagos)
                    metodo_gasto = 'Efectivo' if es_pago_efectivo else 'Interno'
                    metodo_movimiento = 'Efectivo' if es_pago_efectivo else 'SISTEMA'

                    # 4. Registrar Gasto Interno (Para cuadrar caja)
                    cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Canje Puntos'")
                    cat_pts = cursor.fetchone()
                    cat_pts_id = cat_pts['id'] if cat_pts else None
                    if not cat_pts_id:
                        cursor.execute("INSERT INTO categorias_gastos (nombre, descripcion) VALUES ('Canje Puntos', 'Redención de Puntos') RETURNING id")
                        cat_pts_id = cursor.fetchone()['id']
                    
                    cursor.execute("""
                        INSERT INTO gastos (sucursal_id, categoria_gasto_id, caja_sesion_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id)
                        VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s, %s)
                    """, (sucursal_id, cat_pts_id, caja_id, f"Canje Puntos Venta #{serie_comprobante}-{numero_comprobante_str}", monto_desc_puntos, metodo_gasto, current_user.id))

                    # 5. Registrar Movimiento Egreso
                    cursor.execute("""
                        INSERT INTO movimientos_caja (tipo, monto, concepto, metodo_pago, usuario_id, caja_sesion_id)
                        VALUES ('EGRESO', %s, %s, %s, %s, %s)
                    """, (monto_desc_puntos, f"Canje Puntos #{serie_comprobante}-{numero_comprobante_str}", metodo_movimiento, current_user.id, caja_id))
                    
                    # 5. Descontar Puntos del Cliente
                    cursor.execute("UPDATE clientes SET puntos_fidelidad = puntos_fidelidad - %s WHERE id = %s", (puntos_canjeados, cliente_id))
                    
                    # 6. Historial
                    cursor.execute("""
                        INSERT INTO puntos_historial (cliente_id, venta_id, monto_puntos, tipo_transaccion, descripcion)
                        VALUES (%s, %s, %s, 'CANJE', %s)
                    """, (cliente_id, venta_id, puntos_canjeados, f"Canje por S/ {monto_desc_puntos:.2f} en Venta #{serie_comprobante}-{numero_comprobante_str}"))

            # 10. (NUEVO) ACUMULAR PUNTOS (Solo Servicios - 1 Sol = 1 Punto)
            if cliente_id:
                try:
                    # Calcular Puntos solo sobre SERVICIOS (aplicando descuento proporcional)
                    monto_servicios_neto = 0
                    if monto_total_bruto > 0:
                        factor_neto = monto_final / monto_total_bruto
                        monto_servicios_neto = subtotal_servicios * factor_neto
                    
                    puntos_ganados = int(monto_servicios_neto) 

                    if puntos_ganados > 0:
                        # Actualizar saldo cliente
                        cursor.execute("UPDATE clientes SET puntos_fidelidad = COALESCE(puntos_fidelidad, 0) + %s WHERE id = %s", (puntos_ganados, cliente_id))
                        # Registrar historial
                        cursor.execute("""
                            INSERT INTO puntos_historial (cliente_id, venta_id, monto_puntos, tipo_transaccion, descripcion)
                            VALUES (%s, %s, %s, 'ACUMULA', %s)
                        """, (cliente_id, venta_id, puntos_ganados, f"Puntos por Venta #{serie_comprobante}-{numero_comprobante_str}"))
                except Exception as e:
                    print(f"Error acumulando puntos: {e}") 

            db_conn.commit()
            flash(f'Venta registrada: {serie_comprobante}-{numero_comprobante_str}', 'success')
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

        except Exception as e:
            if db_conn: db_conn.rollback()
            flash(f"Error al procesar la venta: {e}", "danger")
            return redirect(url_for('main.nueva_venta'))
        finally:
            if cursor: cursor.close()
    # --- LÓGICA GET (CARGAR FORMULARIO) ---
    try:
        # Recuperar ID de reserva si viene de la agenda
        reserva_id = request.args.get('reserva_id', type=int)
        prefill_data = None

        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            
            # 🟢 NUEVO: Si hay reserva, buscamos sus datos para pre-llenar la venta
            if reserva_id:
                cursor.execute("""
                    SELECT 
                        r.id, r.cliente_id, r.empleado_id, r.servicio_id, 
                        r.precio_cobrado,
                        s.nombre AS servicio_nombre,
                        s.precio AS servicio_precio_base
                    FROM reservas r
                    JOIN servicios s ON r.servicio_id = s.id
                    WHERE r.id = %s
                """, (reserva_id,))
                reserva = cursor.fetchone()
                
                if reserva:
                    # Construimos el objeto que el JavaScript va a leer
                    prefill_data = {
                        "reserva_id": reserva['id'],
                        "cliente_id": reserva['cliente_id'],
                        "empleado_id": reserva['empleado_id'],
                        # Datos del servicio para agregarlo al carrito automáticamente
                        "item_inicial": {
                            "tipo": "servicio", # Minúscula para facilitar JS
                            "id": reserva['servicio_id'],
                            "nombre": reserva['servicio_nombre'],
                            # Usamos el precio pactado, o si es nulo, el precio base
                            "precio": float(reserva['precio_cobrado']) if reserva['precio_cobrado'] else float(reserva['servicio_precio_base']),
                            "cantidad": 1,
                            "empleado_id": reserva['empleado_id']
                        }
                    }
                    flash(f"Datos cargados desde la Reserva #{reserva_id}", "info")

            # 1. Clientes
            cursor.execute("""
                SELECT id, razon_social_nombres, apellidos, telefono, numero_documento,
                       TO_CHAR(fecha_nacimiento, 'YYYY-MM-DD') as fecha_nac_str,
                       cumpleanos_validado, rechazo_dato_cumpleanos
                FROM clientes ORDER BY razon_social_nombres
            """)
            clientes = cursor.fetchall()
            
            for c in clientes:
                nombre_full = f"{c['razon_social_nombres']} {c['apellidos'] or ''}".strip()
                doc = c['numero_documento'] or 'S/D'
                tel = c['telefono'] or ''
                c['texto_busqueda'] = f"{nombre_full} | Doc: {doc} | Tel: {tel}"

            # 2. Empleados Activos
            # 2. Empleados Activos (Filtrados por permiso de Ventas)
            cursor.execute("SELECT id, nombre_display FROM empleados WHERE activo = TRUE AND realiza_ventas = TRUE ORDER BY nombres")
            empleados = cursor.fetchall()
            
            # 3. Servicios Activos
            cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
            servicios = cursor.fetchall()
            
            # 4. Productos Activos
            cursor.execute("SELECT id, nombre, precio_venta, stock_actual FROM productos WHERE activo = TRUE ORDER BY nombre")
            productos = cursor.fetchall()
            
            # 5. Campañas Vigentes
            cursor.execute("SELECT id, nombre FROM campanas WHERE activo = TRUE AND CURRENT_DATE BETWEEN fecha_inicio AND fecha_fin")
            campanas = cursor.fetchall()
            
            return render_template('ventas/form_venta.html', # Asegúrate que tu archivo se llama así, o 'nueva_venta.html'
                                   clientes=clientes, 
                                   empleados=empleados,
                                   servicios=servicios, 
                                   productos=productos,
                                   campanas=campanas, 
                                   prefill_data=prefill_data, # <--- IMPORTANTE: Enviamos los datos
                                   hoy=date.today().strftime('%d/%m/%Y'))
                                   
    except Exception as e:
        flash(f"Error cargando formulario: {e}", "danger")
        return redirect(url_for('main.index'))
  
        
@main_bp.route('/ventas/editar/<int:venta_id>', methods=['GET', 'POST'])
@login_required
def editar_venta(venta_id):
    db_conn = get_db()
    
    # --- LÓGICA POST (GUARDAR CAMBIOS SIMPLES) ---
    if request.method == 'POST':
        try:
            # 1. Recoger Datos Editables
            # Nota: El tipo, serie y número NO se recogen porque no se pueden cambiar aquí.
            
            # Gestión del Cliente (Igual que antes para permitir corregir el cliente)
            cliente_id = request.form.get('cliente_id')
            nuevo_doc = request.form.get('nuevo_cliente_doc')
            nuevo_nombre = request.form.get('nuevo_cliente_nombre').strip().title() if request.form.get('nuevo_cliente_nombre') else None
            nuevo_dir = request.form.get('nuevo_cliente_dir')
            
            with db_conn.cursor() as cursor:
                if nuevo_doc and nuevo_nombre:
                    cursor.execute("SELECT id FROM clientes WHERE numero_documento = %s", (nuevo_doc,))
                    res_cli = cursor.fetchone()
                    tipo_doc = 'RUC' if len(nuevo_doc) == 11 else 'DNI'
                    if res_cli:
                        cliente_id = res_cli[0]
                        cursor.execute("UPDATE clientes SET razon_social_nombres=%s, direccion=%s WHERE id=%s", (nuevo_nombre, nuevo_dir, cliente_id))
                    else:
                        cursor.execute("INSERT INTO clientes (tipo_documento, numero_documento, razon_social_nombres, direccion) VALUES (%s, %s, %s, %s) RETURNING id", (tipo_doc, nuevo_doc, nuevo_nombre, nuevo_dir))
                        cliente_id = cursor.fetchone()[0]
            
            if not cliente_id or str(cliente_id) == 'API_NEW': cliente_id = None 

            empleado_id = request.form.get('empleado_id')
            fecha_venta_str = request.form.get('fecha_venta')
            notas_venta = request.form.get('notas_venta')
            estado_pago_calculado = request.form.get('estado_pago')

            # Pagos
            pagos_json = request.form.get('pagos_json')
            lista_pagos = json.loads(pagos_json) if pagos_json else []

            with db_conn.cursor() as cursor_update:
                # 2. Actualizar Venta (SIN CAMBIAR SERIE NI TIPO)
                sql_update_venta = """
                    UPDATE ventas 
                    SET cliente_receptor_id = %s,
                        empleado_id = %s,
                        fecha_venta = %s,
                        notas_venta = %s,
                        estado_pago = %s
                        -- NO actualizamos tipo_comprobante, serie, numero ni estado_sunat
                    WHERE id = %s
                """
                cursor_update.execute(sql_update_venta, (
                    cliente_id, 
                    empleado_id, 
                    fecha_venta_str, 
                    notas_venta, 
                    estado_pago_calculado,
                    venta_id
                ))

                # 3. Actualizar Pagos
                cursor_update.execute("DELETE FROM venta_pagos WHERE venta_id = %s", (venta_id,))
                sql_insert_pago = "INSERT INTO venta_pagos (venta_id, metodo_pago, monto, referencia_pago, fecha_pago) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)"
                for pago in lista_pagos:
                    metodo = pago.get('metodo_pago') or 'Efectivo'
                    cursor_update.execute(sql_insert_pago, (venta_id, metodo, float(pago.get('monto', 0)), pago.get('referencia_pago')))

            db_conn.commit()
            flash('Datos de la venta actualizados correctamente.', 'success')
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

        except Exception as e:
            if db_conn: db_conn.rollback()
            current_app.logger.error(f"Error editando venta {venta_id}: {e}")
            flash(f"Error al guardar cambios: {e}", "danger")
            return redirect(url_for('main.editar_venta', venta_id=venta_id))

    # --- LÓGICA GET (CARGAR FORMULARIO) ---
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            sql_venta = """
                SELECT v.*, v.cliente_receptor_id as cliente_id,
                       c.razon_social_nombres as cliente_nombre_actual,
                       TO_CHAR(v.fecha_venta, 'YYYY-MM-DD"T"HH24:MI') as fecha_venta_str
                FROM ventas v 
                LEFT JOIN clientes c ON v.cliente_receptor_id = c.id
                WHERE v.id = %s
            """
            cursor.execute(sql_venta, (venta_id,))
            venta_actual = cursor.fetchone()
            
            if not venta_actual: return redirect(url_for('main.listar_ventas'))

            cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,))
            items_venta = cursor.fetchall()

            cursor.execute("SELECT metodo_pago, monto, referencia_pago FROM venta_pagos WHERE venta_id = %s", (venta_id,))
            pagos_venta = cursor.fetchall()
            for p in pagos_venta: p['monto'] = float(p['monto'])
            pagos_venta_json = json.dumps(pagos_venta)

            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()
            
            cursor.execute("""
                SELECT id, razon_social_nombres, apellidos, numero_documento 
                FROM clientes ORDER BY razon_social_nombres
            """)
            clientes = cursor.fetchall()
            for c in clientes:
                c['texto_busqueda'] = f"{c['razon_social_nombres']} {c['apellidos'] or ''} | {c['numero_documento'] or ''}"

            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY nombres")
            empleados = cursor.fetchall()

            # Ya no necesitamos enviar 'tipos_comprobante' porque es readonly
            metodos_pago = ['Efectivo', 'Yape', 'Plin', 'Tarjeta', 'Transferencia']

            return render_template('ventas/form_editar_venta.html',
                                   titulo_form=f"Editar Datos Venta #{venta_actual['numero_comprobante']}",
                                   action_url=url_for('main.editar_venta', venta_id=venta_id),
                                   venta=venta_actual,
                                   items_venta=items_venta,
                                   pagos_venta_json=pagos_venta_json,
                                   sucursales=sucursales,
                                   clientes=clientes,
                                   empleados=empleados,
                                   metodos_pago=metodos_pago)
    except Exception as e:
        flash(f"Error cargando: {e}", "danger")
        return redirect(url_for('main.listar_ventas'))
    

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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except (ValueError, Exception, Exception) as e:
        if db_conn and db_conn.in_transaction:
            db_conn.rollback()
        flash(f"Ocurrió un error inesperado al anular la venta: {e}", "danger")
        current_app.logger.error(f"Error en anular_venta (ID: {venta_id}): {e}")

    return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

@main_bp.route('/ventas/detalle/<int:venta_id>')
@login_required
def ver_detalle_venta(venta_id):
    """
    Muestra el detalle completo de una venta.
    Versión corregida con el alias 'venta_id'.
    """
    db_conn = get_db()
    venta_actual, items_actuales, pagos_actuales = None, [], []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
        flash(f"Error al cargar el detalle de la venta: {err}", "danger")
        return redirect(url_for('main.listar_ventas'))

    return render_template('ventas/ver_venta.html',
                           venta=venta_actual,
                           items=items_actuales,
                           pagos=pagos_actuales,
                           titulo_pagina=f"Detalle de Venta #{venta_actual['serie_comprobante']}-{venta_actual['numero_comprobante']}")

@main_bp.route('/ventas/ticket/<int:venta_id>')
@login_required
def ver_ticket(venta_id):
    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Datos Cabecera
            cursor.execute("""
                SELECT v.*, 
                       COALESCE(c.razon_social_nombres, 'Cliente Varios') as cliente_nombre,
                       c.numero_documento as cliente_doc,
                       c.direccion as cliente_dir,
                       e.nombres as empleado_nombre,
                       s.nombre as sucursal_nombre,
                       s.direccion as sucursal_direccion
                FROM ventas v
                LEFT JOIN clientes c ON v.cliente_receptor_id = c.id
                JOIN empleados e ON v.empleado_id = e.id
                JOIN sucursales s ON v.sucursal_id = s.id
                WHERE v.id = %s
            """, (venta_id,))
            venta = cursor.fetchone()

            if not venta:
                return "Venta no encontrada", 404

            # 2. Ítems
            cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,))
            items = cursor.fetchall()

            # 3. Pagos
            cursor.execute("SELECT * FROM venta_pagos WHERE venta_id = %s", (venta_id,))
            pagos = cursor.fetchall()

            return render_template('ventas/ticket.html', venta=venta, items=items, pagos=pagos)

    except Exception as e:
        return f"Error generando ticket: {e}", 500

    
@main_bp.route('/ventas/imprimir/<int:venta_id>')
@login_required
def imprimir_ticket_venta(venta_id):
    """
    Prepara los datos y muestra una vista de ticket para imprimir.
    """
    db_conn = get_db()
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
        flash(f"Error al generar el ticket de venta: {err}", "danger")
        return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

    return render_template('ventas/ticket_venta.html',
                           venta=venta_actual,
                           items=items_actuales,
                           pagos=pagos_actuales)

    
@main_bp.route('/ventas')
@login_required
def listar_ventas():
    if not current_user.can('ver_ventas'):
        flash('Acceso denegado', 'danger')
        return redirect(url_for('main.index'))
    """
    Muestra una lista de todas las ventas registradas.
    Versión corregida con el alias 'venta_id' verificado.
    """
    db_conn = get_db()
    lista_de_ventas = []
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # --- CORRECCIÓN CLAVE ---
            # Nos aseguramos de que la columna v.id se renombre a 'venta_id'
            sql = """
                SELECT 
                    v.id AS venta_id, 
                    v.fecha_venta, 
                    v.monto_final_venta, 
                    v.estado_pago,
                    v.tipo_comprobante,
                    v.estado_sunat,
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
            
    except Exception as err:
        flash(f"Error al acceder al historial de ventas: {err}", "danger")
        current_app.logger.error(f"Error en listar_ventas: {err}")
        
    return render_template('ventas/lista_ventas.html', 
                           ventas=lista_de_ventas,
                           titulo_pagina="Historial de Ventas")

@main_bp.route('/ventas/eliminar/<int:venta_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_venta_nota_venta(venta_id):
    """
    Permite eliminar una venta SOLO si es una Nota de Venta.
    Elimina en cascada (items y pagos) y luego la venta.
    """
    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Verificar que sea Nota de Venta
            cursor.execute("SELECT tipo_comprobante FROM ventas WHERE id = %s", (venta_id,))
            venta = cursor.fetchone()
            
            if not venta:
                flash("Venta no encontrada.", "warning")
                return redirect(url_for('main.listar_ventas'))
            
            if venta['tipo_comprobante'] != 'Nota de Venta':
                flash("Solo se pueden eliminar Notas de Venta.", "danger")
                return redirect(url_for('main.listar_ventas'))

            # 2. Eliminar items y pagos (si no hay cascade en BD)
            cursor.execute("DELETE FROM venta_items WHERE venta_id = %s", (venta_id,))
            cursor.execute("DELETE FROM venta_pagos WHERE venta_id = %s", (venta_id,))
            cursor.execute("DELETE FROM ventas WHERE id = %s", (venta_id,))
            
            db_conn.commit()
            flash("Nota de Venta eliminada exitosamente.", "success")
            
    except Exception as e:
        db_conn.rollback()
        current_app.logger.error(f"Error eliminando venta {venta_id}: {e}")
        flash(f"Error al eliminar la venta: {e}", "danger")

    return redirect(url_for('main.listar_ventas'))
    
    
@main_bp.route('/configuracion/sucursales')
@login_required
@admin_required
def listar_sucursales():
    """
    Muestra la lista de todas las sucursales del negocio.
    """
    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM sucursales ORDER BY nombre")
        lista_de_sucursales = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
    y procesa la creación de la sucursal (POST), incluyendo redes sociales.
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

        # --- CAMPOS NUEVOS DE REDES SOCIALES ---
        facebook_url = request.form.get('facebook_url', '').strip()
        instagram_url = request.form.get('instagram_url', '').strip()
        tiktok_url = request.form.get('tiktok_url', '').strip()
        whatsapp_numero_raw = request.form.get('whatsapp_numero', '').strip()

        # Limpiar WhatsApp: quitar espacios, guiones, etc.
        whatsapp_numero = ''.join(filter(str.isdigit, whatsapp_numero_raw))

        if not nombre:
            flash('El nombre de la sucursal es obligatorio.', 'warning')
            return render_template('configuracion/form_sucursal.html', 
                                   form_data=request.form, 
                                   es_nueva=True, 
                                   titulo_form=form_titulo,
                                   action_url=action_url_form)

        cursor_insert = None
        try:
            db = get_db()
            cursor_insert = db.cursor()
            # --- SQL ACTUALIZADO ---
            sql = """INSERT INTO sucursales 
                        (nombre, direccion, ciudad, telefono, email, 
                         codigo_establecimiento_sunat, activo,
                         facebook_url, instagram_url, tiktok_url, whatsapp_numero) 
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
            val = (nombre, 
                   (direccion or None), (ciudad or None), (telefono or None), (email or None), 
                   (codigo_sunat or None), activo,
                   (facebook_url or None), (instagram_url or None), (tiktok_url or None), (whatsapp_numero or None))
            
            cursor_insert.execute(sql, val)
            db.commit()
            flash(f'Sucursal "{nombre}" registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_sucursales'))
        except Exception as err:
            db.rollback()
            # Asumiendo que 'nombre' tiene una constraint UNIQUE
            if hasattr(err, 'pgcode') and err.pgcode == '23505': 
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM sucursales WHERE id = %s", (sucursal_id,))
        sucursal_actual = cursor.fetchone()
    except Exception as err:
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

        # --- CAMPOS NUEVOS DE REDES SOCIALES ---
        facebook_url_nuevo = request.form.get('facebook_url', '').strip()
        instagram_url_nuevo = request.form.get('instagram_url', '').strip()
        tiktok_url_nuevo = request.form.get('tiktok_url', '').strip()
        whatsapp_numero_raw_nuevo = request.form.get('whatsapp_numero', '').strip()
        
        # Limpiar WhatsApp
        whatsapp_numero_nuevo = ''.join(filter(str.isdigit, whatsapp_numero_raw_nuevo))

        errores = []
        if not nombre_nuevo:
            errores.append('El nombre de la sucursal es obligatorio.')

        # Validar unicidad del nombre si ha cambiado
        if nombre_nuevo and nombre_nuevo.lower() != sucursal_actual.get('nombre', '').lower():
            try:
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM sucursales WHERE nombre = %s AND id != %s", (nombre_nuevo, sucursal_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra sucursal con el nombre "{nombre_nuevo}".')
            except Exception as err_check:
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
                # --- SQL ACTUALIZADO ---
                sql_update = """UPDATE sucursales SET 
                                    nombre = %s, direccion = %s, ciudad = %s, telefono = %s, 
                                    email = %s, codigo_establecimiento_sunat = %s, activo = %s,
                                    facebook_url = %s, instagram_url = %s, tiktok_url = %s, whatsapp_numero = %s
                                WHERE id = %s"""
                val_update = (nombre_nuevo, 
                              (direccion_nueva or None),
                              (ciudad_nueva or None),
                              (telefono_nuevo or None),
                              (email_nuevo or None),
                              (codigo_sunat_nuevo or None),
                              activo_nuevo,
                              (facebook_url_nuevo or None),
                              (instagram_url_nuevo or None),
                              (tiktok_url_nuevo or None),
                              (whatsapp_numero_nuevo or None),
                              sucursal_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'Sucursal "{nombre_nuevo}" actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_sucursales'))
            except Exception as err_upd:
                db_conn.rollback()
                # Adaptado para psycopg2 - el código de error de unicidad es '23505'
                if hasattr(err_upd, 'pgcode') and err_upd.pgcode == '23505':
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
        
    except Exception as err:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Consulta actualizada con JOIN a la tabla 'sucursales'
        sql = """
            SELECT 
                cs.id, cs.tipo_comprobante, cs.serie, 
                cs.ultimo_numero, cs.activo,
                s.nombre AS sucursal_nombre 
            FROM series_comprobantes cs
            JOIN sucursales s ON cs.sucursal_id = s.id
            ORDER BY s.nombre, cs.tipo_comprobante, cs.serie
        """
        cursor.execute(sql)
        lista_de_series = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor.fetchall()
    except Exception as err_load:
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
        ultimo_numero_str = request.form.get('ultimo_numero', '0')
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
        
        ultimo_numero = 0
        try:
            ultimo_numero = int(ultimo_numero_str)
            if ultimo_numero < 0:
                errores.append("El último número no puede ser negativo.")
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
            sql = "INSERT INTO series_comprobantes (sucursal_id, tipo_comprobante, serie, ultimo_numero, activo) VALUES (%s, %s, %s, %s, %s)"
            val = (sucursal_id, tipo_comprobante, serie, ultimo_numero, activo)
            cursor_insert.execute(sql, val)
            db_conn.commit()
            flash(f'La serie "{serie}" para "{tipo_comprobante}" ha sido registrada exitosamente!', 'success')
            return redirect(url_for('main.listar_series'))
        except Exception as err:
            db_conn.rollback()
            if hasattr(err, 'pgcode') and err.pgcode == '23505': # Error de uq_sucursal_tipo_serie
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM series_comprobantes WHERE id = %s", (serie_id,))
        serie_actual = cursor.fetchone()
    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
        sucursales_activas = cursor.fetchall()
    except Exception as err_load:
        flash(f"Error al cargar sucursales para el formulario: {err_load}", "danger")
    finally:
        if cursor: cursor.close()
    
    form_titulo = f"Editar Serie: {serie_actual.get('serie', '')}"
    action_url_form = url_for('main.editar_serie', serie_id=serie_id)

    if request.method == 'POST':
        sucursal_id_str = request.form.get('sucursal_id')
        tipo_comprobante = request.form.get('tipo_comprobante')
        serie_nueva = request.form.get('serie', '').strip().upper()
        ultimo_numero_str = request.form.get('ultimo_numero', '0')
        activo_nuevo = 'activo' in request.form

        errores = []
        sucursal_id = None
        if not sucursal_id_str: errores.append("Debe seleccionar una sucursal.")
        else:
            try: sucursal_id = int(sucursal_id_str)
            except ValueError: errores.append("Sucursal seleccionada inválida.")
        
        if not tipo_comprobante: errores.append("Debe seleccionar un tipo de comprobante.")
        if not serie_nueva: errores.append("El código de la serie es obligatorio.")
        
        ultimo_numero = 0
        try:
            ultimo_numero = int(ultimo_numero_str)
            if ultimo_numero < 0:
                errores.append("El último número no puede ser negativo.")
        except (ValueError, TypeError):
            errores.append("El último número debe ser un número entero.")
        
        # Validar unicidad de la combinación (sucursal, tipo, serie) si ha cambiado
        if (sucursal_id != serie_actual.get('sucursal_id') or 
            tipo_comprobante != serie_actual.get('tipo_comprobante') or 
            serie_nueva.lower() != serie_actual.get('serie', '').lower()):
            try:
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM series_comprobantes WHERE sucursal_id = %s AND tipo_comprobante = %s AND serie = %s AND id != %s", 
                               (sucursal_id, tipo_comprobante, serie_nueva, serie_id))
                if cursor.fetchone():
                    errores.append(f'Error: La combinación de sucursal, tipo y serie ("{serie_nueva}") ya existe.')
            except Exception as err_check:
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
                sql_update = """UPDATE series_comprobantes SET 
                                    sucursal_id = %s, tipo_comprobante = %s, serie = %s, 
                                    ultimo_numero = %s, activo = %s
                                WHERE id = %s"""
                val_update = (sucursal_id, tipo_comprobante, serie_nueva, 
                              ultimo_numero, activo_nuevo, serie_id)
                cursor.execute(sql_update, val_update)
                db_conn.commit()
                flash(f'La serie "{serie_nueva}" ha sido actualizada exitosamente!', 'success')
                return redirect(url_for('main.listar_series'))
            except Exception as err_upd:
                db_conn.rollback()
                if hasattr(err_upd, 'pgcode') and err_upd.pgcode == '23505':
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Obtener el estado actual de la serie
        cursor.execute("SELECT id, serie, tipo_comprobante, activo FROM series_comprobantes WHERE id = %s", (serie_id,))
        serie_actual = cursor.fetchone()

        if not serie_actual:
            flash(f'Configuración de serie con ID {serie_id} no encontrada.', 'warning')
            return redirect(url_for('main.listar_series'))

        nuevo_estado_activo = not serie_actual['activo']
        
        # Actualizar el estado en la base de datos
        # Reutilizamos el cursor ya que la operación de lectura ya terminó
        cursor.execute("UPDATE series_comprobantes SET activo = %s WHERE id = %s", (nuevo_estado_activo, serie_id))
        db_conn.commit()
        
        mensaje_estado = "activada" if nuevo_estado_activo else "desactivada"
        flash(f'La serie "{serie_actual["serie"]}" para "{serie_actual["tipo_comprobante"]}" ha sido {mensaje_estado} exitosamente.', 'success')
        
    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        sql = """
            SELECT serie FROM series_comprobantes 
            WHERE sucursal_id = %s AND tipo_comprobante = %s AND activo = TRUE
            ORDER BY serie
        """
        cursor.execute(sql, (sucursal_id, tipo_comprobante))
        resultados = cursor.fetchall()
        # Creamos una lista simple de strings con las series
        series_disponibles = [row['serie'] for row in resultados]
    except Exception as err:
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_gastos ORDER BY nombre")
        lista_de_categorias = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
        except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT id, nombre, descripcion FROM categorias_gastos WHERE id = %s", (categoria_id,))
        categoria_actual = cursor.fetchone()
    except Exception as err:
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
                cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = %s AND id != %s", (nombre_nuevo, categoria_id))
                if cursor.fetchone():
                    errores.append(f'Error: Ya existe otra categoría de gasto con el nombre "{nombre_nuevo}".')
            except Exception as err_check:
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
            except Exception as err_upd:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

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
            
    except Exception as err:
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
def listar_gastos():
    if not current_user.can('ver_finanzas'):
        flash('Acceso denegado', 'danger')
        return redirect(url_for('main.index'))
    """
    Muestra una lista de todos los gastos registrados.
    """
    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    except Exception as err:
        flash(f"Error al acceder a los gastos: {err}", "danger")
        current_app.logger.error(f"Error en listar_gastos: {err}")
        lista_de_gastos = []
        
    return render_template('finanzas/lista_gastos.html', 
                           gastos=lista_de_gastos,
                           titulo_pagina="Historial de Gastos")

@main_bp.route('/finanzas/gastos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_gasto():
    # --- 0. VERIFICACIONES DE SEGURIDAD ---
    es_admin = getattr(current_user, 'rol_nombre', '') == 'Administrador'
    es_cajero = getattr(current_user, 'rol_nombre', '') == 'Cajero'
    
    if not es_admin and not es_cajero and not current_user.can('ver_finanzas'):
        flash('Acceso denegado', 'danger')
        return redirect(url_for('main.index'))
    
    sucursal_id = session.get('sucursal_id')
    if not sucursal_id:
        flash("Debe seleccionar una sucursal para registrar gastos.", "warning")
        return redirect(url_for('main.index'))

    db_conn = get_db()

    # ==============================================================================
    # --- 1. VALIDACIÓN CRÍTICA: CAJA ABIERTA (NUEVO) ---
    # ==============================================================================
    caja_id_activa = None
    try:
        with db_conn.cursor() as cursor_val:
            cursor_val.execute("""
                SELECT id FROM caja_sesiones 
                WHERE usuario_id = %s AND sucursal_id = %s AND estado = 'Abierta'
                LIMIT 1
            """, (current_user.id, sucursal_id))
            row_caja = cursor_val.fetchone()

            if not row_caja:
                flash("⛔ ACCESO DENEGADO: Debes ABRIR CAJA para registrar salidas de dinero (gastos).", "danger")
                return redirect(url_for('main.index'))
            
            caja_id_activa = row_caja[0] # Guardamos el ID para usarlo al guardar
    except Exception as e:
        flash(f"Error verificando estado de caja: {e}", "danger")
        return redirect(url_for('main.index'))
    # ==============================================================================

    # 2. CARGAR DATOS PARA EL FORMULARIO (GET)
    categorias_gastos = []
    colaboradores_activos = []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Categorías
            cursor.execute("SELECT id, nombre FROM categorias_gastos ORDER BY nombre")
            categorias_gastos = cursor.fetchall()
            
            # Colaboradores
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor.fetchall()
    except Exception as err_load:
        flash(f"Error al cargar datos auxiliares: {err_load}", "danger")

    form_titulo = "Registrar Nuevo Gasto"
    action_url_form = url_for('main.nuevo_gasto')

    # --- LÓGICA POST (GUARDAR GASTO) ---
    if request.method == 'POST':
        # Recoger datos
        categoria_gasto_id_str = request.form.get('categoria_gasto_id')
        fecha_str = request.form.get('fecha')
        descripcion = request.form.get('descripcion')
        monto_str = request.form.get('monto')
        metodo_pago = request.form.get('metodo_pago')
        empleado_beneficiario_id_str = request.form.get('empleado_beneficiario_id')

        # Campos del comprobante
        comprobante_tipo = request.form.get('comprobante_tipo', '').strip()
        comprobante_serie = request.form.get('comprobante_serie', '').strip()
        comprobante_numero = request.form.get('comprobante_numero', '').strip()
        comprobante_ruc_emisor = request.form.get('comprobante_ruc_emisor', '').strip()
        comprobante_razon_social_emisor = request.form.get('comprobante_razon_social_emisor', '').strip()
        
        errores = []
        if not categoria_gasto_id_str: errores.append("Seleccione una categoría.")
        if not fecha_str: errores.append("La fecha es obligatoria.")
        if not descripcion: errores.append("La descripción es obligatoria.")
        if not monto_str: errores.append("El monto es obligatorio.")
        
        if not metodo_pago: metodo_pago = 'Efectivo' 

        monto = 0.0
        try:
            monto = float(monto_str)
            if monto <= 0: errores.append("El monto debe ser positivo.")
        except:
            errores.append("Monto inválido.")
        
        # NOTA: Ya no necesitamos "buscar" la caja aquí, porque la validamos al inicio.
        # Usamos directamente 'caja_id_activa' que obtuvimos arriba.

        if errores:
            for error in errores: flash(error, 'warning')
        else:
            # 4. INSERTAR GASTO
            try:
                with db_conn.cursor() as cursor:
                    sql = """INSERT INTO gastos 
                                (sucursal_id, categoria_gasto_id, fecha, descripcion, monto, metodo_pago, 
                                 registrado_por_colaborador_id, empleado_beneficiario_id, caja_sesion_id,
                                 comprobante_tipo, comprobante_serie, comprobante_numero, 
                                 comprobante_ruc_emisor, comprobante_razon_social_emisor)
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    
                    empleado_beneficiario_id = int(empleado_beneficiario_id_str) if empleado_beneficiario_id_str else None

                    val = (sucursal_id, int(categoria_gasto_id_str), fecha_str, descripcion, monto, 
                           metodo_pago, current_user.id, empleado_beneficiario_id, caja_id_activa, # <--- USAMOS LA CAJA VALIDADA
                           comprobante_tipo or None, comprobante_serie or None,
                           comprobante_numero or None, comprobante_ruc_emisor or None,
                           comprobante_razon_social_emisor or None
                          )
                    cursor.execute(sql, val)
                
                db_conn.commit()
                flash("✅ Gasto registrado correctamente.", "success")
                return redirect(url_for('main.listar_gastos'))
                
            except Exception as err:
                db_conn.rollback()
                flash(f"Error al guardar gasto: {err}", "danger")
                # current_app.logger.error(f"Error nuevo_gasto POST: {err}")
        
        # Si hubo error en validación o inserción, volver al formulario
        return render_template('finanzas/form_gasto.html', 
                               form_data=request.form, es_nueva=True, 
                               titulo_form=form_titulo,
                               action_url=action_url_form, 
                               categorias_gastos=categorias_gastos, 
                               colaboradores=colaboradores_activos,
                               hoy=date.today().strftime('%Y-%m-%d'))

    # --- LÓGICA GET ---
    return render_template('finanzas/form_gasto.html', 
                           es_nueva=True, 
                           titulo_form=form_titulo,
                           action_url=action_url_form, 
                           categorias_gastos=categorias_gastos, 
                           colaboradores=colaboradores_activos,
                           hoy=date.today().strftime('%Y-%m-%d'))
    
@main_bp.route('/finanzas/gastos/editar/<int:gasto_id>', methods=['GET', 'POST'])
@login_required
def editar_gasto(gasto_id):
    db_conn = get_db()
    
    # 1. Buscar Gasto Actual
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM gastos WHERE id = %s", (gasto_id,))
            gasto_actual = cursor.fetchone()
            
            if not gasto_actual:
                flash(f"Gasto no encontrado.", "warning")
                return redirect(url_for('main.listar_gastos'))

            # Cargar Maestros
            cursor.execute("SELECT id, nombre FROM categorias_gastos ORDER BY nombre")
            categorias_gastos = cursor.fetchall()
            
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor.fetchall()
            
    except Exception as e:
        flash(f"Error al cargar datos: {e}", "danger")
        return redirect(url_for('main.listar_gastos'))

    form_titulo = f"Editar Gasto #{gasto_id}"
    action_url_form = url_for('main.editar_gasto', gasto_id=gasto_id)

    # --- LÓGICA POST (ACTUALIZAR) ---
    if request.method == 'POST':
        # Recoger datos
        # Sucursal NO se edita (se mantiene la original del gasto o la de sesión)
        # sucursal_id = gasto_actual['sucursal_id'] 
        
        categoria_gasto_id_str = request.form.get('categoria_gasto_id')
        fecha_str = request.form.get('fecha')
        descripcion = request.form.get('descripcion')
        monto_str = request.form.get('monto')
        metodo_pago = request.form.get('metodo_pago')
        empleado_beneficiario_id_str = request.form.get('empleado_beneficiario_id')

        # Comprobante
        comprobante_tipo = request.form.get('comprobante_tipo', '').strip()
        comprobante_serie = request.form.get('comprobante_serie', '').strip()
        comprobante_numero = request.form.get('comprobante_numero', '').strip()
        comprobante_ruc_emisor = request.form.get('comprobante_ruc_emisor', '').strip()
        comprobante_razon_social_emisor = request.form.get('comprobante_razon_social_emisor', '').strip()

        errores = []
        if not descripcion: errores.append("Descripción obligatoria.")
        
        # Validación monto
        monto = 0.0
        try:
            monto = float(monto_str)
            if monto <= 0: errores.append("Monto debe ser positivo.")
        except:
            errores.append("Monto inválido.")

        if errores:
            for error in errores: flash(error, 'warning')
            return render_template('finanzas/form_gasto.html', 
                                   es_nueva=False, form_data=request.form, gasto=gasto_actual,
                                   titulo_form=form_titulo, action_url=action_url_form,
                                   categorias_gastos=categorias_gastos, colaboradores=colaboradores_activos)

        try:
            with db_conn.cursor() as cursor:
                sql_update = """UPDATE gastos SET 
                                    categoria_gasto_id = %s, 
                                    fecha = %s, 
                                    descripcion = %s, 
                                    monto = %s, 
                                    metodo_pago = %s, 
                                    empleado_beneficiario_id = %s, -- Faltaba este
                                    comprobante_tipo = %s, 
                                    comprobante_serie = %s, 
                                    comprobante_numero = %s, 
                                    comprobante_ruc_emisor = %s, 
                                    comprobante_razon_social_emisor = %s
                                WHERE id = %s"""
                
                # CORRECCIÓN DE TIPOS INT/NONE
                cat_id = int(categoria_gasto_id_str)
                beneficiario_id = int(empleado_beneficiario_id_str) if empleado_beneficiario_id_str else None

                val_update = (
                    cat_id, fecha_str, descripcion, monto, metodo_pago, 
                    beneficiario_id,
                    comprobante_tipo or None, comprobante_serie or None,
                    comprobante_numero or None, comprobante_ruc_emisor or None,
                    comprobante_razon_social_emisor or None,
                    gasto_id
                )
                cursor.execute(sql_update, val_update)
            
            db_conn.commit()
            flash("Gasto actualizado exitosamente.", "success")
            return redirect(url_for('main.listar_gastos'))
            
        except Exception as err:
            db_conn.rollback()
            flash(f"Error al actualizar: {err}", "danger")
            current_app.logger.error(f"Error editar_gasto: {err}")
            return redirect(url_for('main.editar_gasto', gasto_id=gasto_id))

    # --- LÓGICA GET ---
    if gasto_actual.get('fecha'):
        gasto_actual['fecha'] = gasto_actual['fecha'].strftime('%Y-%m-%d')
        
    return render_template('finanzas/form_gasto.html', 
                           es_nueva=False, 
                           titulo_form=form_titulo,
                           action_url=action_url_form,
                           gasto=gasto_actual,
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
            
    except Exception as err:
        db_conn.rollback()
        flash(f"Error al eliminar el registro de gasto: {err}", "danger")
        current_app.logger.error(f"Error DB en eliminar_gasto (ID: {gasto_id}): {err}")
    finally:
        if cursor:
            cursor.close()

    return redirect(url_for('main.listar_gastos'))


@main_bp.route('/finanzas/caja/detalle/<int:sesion_id>')
@login_required
def ver_detalle_caja(sesion_id):
    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Datos de la Sesión
            cursor.execute("""
                SELECT cs.*, e.nombres || ' ' || e.apellidos as cajero_nombre, s.nombre as sucursal_nombre
                FROM caja_sesiones cs
                JOIN empleados e ON cs.usuario_id = e.id
                JOIN sucursales s ON cs.sucursal_id = s.id
                WHERE cs.id = %s
            """, (sesion_id,))
            sesion = cursor.fetchone()
            
            if not sesion:
                flash("Sesión no encontrada.", "danger")
                return redirect(url_for('main.listar_historial_caja'))

            # 2. Obtener Ventas (Tienen fecha y hora)
            cursor.execute("""
                SELECT id, fecha_venta as fecha, 'Venta' as tipo, 
                       'Venta #' || COALESCE(serie_comprobante, '') || '-' || COALESCE(numero_comprobante, 'S/N') as descripcion,
                       monto_final_venta as monto, 'Ingreso' as flujo,
                       'Efectivo' as metodo_pago -- Simplificación para visualización
                FROM ventas 
                WHERE caja_sesion_id = %s AND estado_pago != 'Anulado'
            """, (sesion_id,))
            ventas = cursor.fetchall()

            # 3. Obtener Gastos (Tienen fecha sola, a veces)
            cursor.execute("""
                SELECT id, fecha, 'Gasto' as tipo, 
                       descripcion, monto, 'Egreso' as flujo,
                       metodo_pago
                FROM gastos 
                WHERE caja_sesion_id = %s
            """, (sesion_id,))
            gastos = cursor.fetchall()

            # 4. UNIFICAR Y NORMALIZAR FECHAS (Solución del Error)
            movimientos = ventas + gastos
            
            for mov in movimientos:
                fecha_dato = mov.get('fecha')
                # Si es tipo 'date' puro (sin hora), lo convertimos a 'datetime' (con hora 00:00)
                # Usamos type() estricto porque datetime es instancia de date
                if type(fecha_dato) is date:
                    mov['fecha'] = datetime.combine(fecha_dato, time.min)
            
            # Ahora sí podemos ordenar
            movimientos.sort(key=lambda x: x['fecha'], reverse=True)

            return render_template('caja/ver_detalle.html', sesion=sesion, movimientos=movimientos)

    except Exception as e:
        # Imprimir el error real en la consola para que lo veas
        import traceback
        traceback.print_exc()
        flash(f"Error al cargar el detalle: {e}", "danger")
        return redirect(url_for('main.listar_historial_caja'))

@main_bp.route('/finanzas/gastos/detalle/<int:gasto_id>')
@login_required
def ver_detalle_gasto(gasto_id):
    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""
                SELECT g.*, cg.nombre as categoria, s.nombre as sucursal,
                       e.nombres || ' ' || e.apellidos as registrado_por
                FROM gastos g
                JOIN categorias_gastos cg ON g.categoria_gasto_id = cg.id
                JOIN sucursales s ON g.sucursal_id = s.id
                LEFT JOIN empleados e ON g.registrado_por_colaborador_id = e.id
                WHERE g.id = %s
            """, (gasto_id,))
            gasto = cursor.fetchone()
        
        # Puedes crear una plantilla 'finanzas/ver_gasto.html' o usar un modal
        # Por ahora, para no romper, mostramos un texto simple o redirigimos
        return f"Detalle del Gasto ID {gasto_id}: {gasto['descripcion']} - S/ {gasto['monto']}"
        
    except Exception as e:
        flash(f"Error al ver gasto: {e}", "danger")
        return redirect(url_for('main.gestionar_caja'))


# --- RUTAS PARA COMPRAS ---

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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre_empresa FROM proveedores WHERE activo = TRUE ORDER BY nombre_empresa")
            proveedores_activos = cursor.fetchall()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
    except Exception as err_load:
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
                RETURNING id
            """
            val_compra = (int(proveedor_id_str), int(sucursal_id_str), fecha_compra_str, (tipo_comprobante or None), (serie_numero_comprobante or None), subtotal_compra, impuestos, total_compra, estado_pago, (notas or None))
            cursor_post.execute(sql_compra, val_compra)
            compra_id = cursor_post.fetchone()[0]

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

        except (ValueError, Exception) as e:
            if db_conn: 
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
    except Exception as err:
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
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
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

    except Exception as err:
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

# --- RUTAS PARA CAJA ---

# -------------------------------------------------------------------------
# GESTIÓN DE CAJA (CORREGIDA)
# -------------------------------------------------------------------------
@main_bp.route('/finanzas/caja', methods=['GET', 'POST'])
@login_required
def gestionar_caja():
    db_conn = get_db()
    sucursal_id = session.get('sucursal_id')
    usuario_id = current_user.id
    
    if not sucursal_id:
        flash("Error: No se detectó sucursal.", "danger")
        return redirect(url_for('main.index'))

    # --- POST: ABRIR CAJA ---
    if request.method == 'POST':
        try:
            monto_base = request.form.get('monto_base')
            monto_adicional = request.form.get('monto_adicional')
            monto_inicial_manual = request.form.get('monto_inicial')

            # Calcular monto final
            if monto_base:
                monto_final = float(monto_base) + float(monto_adicional or 0)
            else:
                monto_final = float(monto_inicial_manual or 0)

            with db_conn.cursor() as cursor:
                cursor.execute("SELECT id FROM caja_sesiones WHERE usuario_id=%s AND estado='Abierta'", (usuario_id,))
                if cursor.fetchone():
                    flash("Ya tienes una caja abierta.", "warning")
                else:
                    cursor.execute("""
                        INSERT INTO caja_sesiones (usuario_id, sucursal_id, monto_inicial, estado, fecha_apertura)
                        VALUES (%s, %s, %s, 'Abierta', CURRENT_TIMESTAMP)
                    """, (usuario_id, sucursal_id, monto_final))
                    db_conn.commit()
                    flash(f"¡Caja abierta con S/ {monto_final:.2f}!", "success")
        except Exception as e:
            db_conn.rollback()
            flash(f"Error al abrir caja: {e}", "danger")
        return redirect(url_for('main.gestionar_caja'))

    # --- GET: VER ESTADO ---
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Buscar sesión abierta
            cursor.execute("""
                SELECT * FROM caja_sesiones 
                WHERE usuario_id = %s AND sucursal_id = %s AND estado = 'Abierta'
            """, (usuario_id, sucursal_id))
            sesion_abierta = cursor.fetchone()

            # CASO A: CAJA CERRADA -> Preparar Apertura
            if not sesion_abierta:
                monto_sugerido = 0.00
                
                cursor.execute("""
                    SELECT monto_final_real, destino_remanente 
                    FROM caja_sesiones 
                    WHERE sucursal_id = %s AND estado = 'Cerrada'
                    ORDER BY fecha_cierre DESC 
                    LIMIT 1
                """, (sucursal_id,))
                ultima_caja = cursor.fetchone()
                
                if ultima_caja and ultima_caja['destino_remanente'] == 'Caja':
                    monto_sugerido = float(ultima_caja['monto_final_real'])

                return render_template('caja/apertura.html', monto_sugerido=monto_sugerido)

            # CASO B: CAJA ABIERTA -> Panel de Gestión
            caja_id = sesion_abierta['id']
            
            # --- CÁLCULO DE TOTALES ---
            
            # 1. Ventas en Efectivo
            cursor.execute("""
                SELECT COALESCE(SUM(vp.monto), 0) as total
                FROM venta_pagos vp JOIN ventas v ON vp.venta_id = v.id
                WHERE v.caja_sesion_id = %s AND vp.metodo_pago = 'Efectivo' AND v.estado_pago != 'Anulado'
            """, (caja_id,))
            total_ventas_efectivo = float(cursor.fetchone()['total'])

            # 2. Propinas en Efectivo (Dinero en custodia)
            # Sumamos las propinas que entraron en efectivo desde que se abrió esta caja
            cursor.execute("""
                SELECT COALESCE(SUM(monto), 0) as total 
                FROM propinas 
                WHERE metodo_pago = 'Efectivo' 
                  AND fecha_registro >= %s 
                  AND entregado_al_barbero = FALSE
            """, (sesion_abierta['fecha_apertura'],))
            total_propinas_efectivo = float(cursor.fetchone()['total'])

            # TOTAL EFECTIVO (Ventas + Propinas)
            total_efectivo = total_ventas_efectivo + total_propinas_efectivo

            # 3. Ventas Digitales
            cursor.execute("""
                SELECT COALESCE(SUM(vp.monto), 0) as total
                FROM venta_pagos vp JOIN ventas v ON vp.venta_id = v.id
                WHERE v.caja_sesion_id = %s AND vp.metodo_pago != 'Efectivo' AND v.estado_pago != 'Anulado'
            """, (caja_id,))
            total_digital = float(cursor.fetchone()['total'])

            # 4. Gastos / Salidas
            cursor.execute("""
                SELECT COALESCE(SUM(monto), 0) as total 
                FROM gastos WHERE caja_sesion_id = %s AND (metodo_pago = 'Efectivo' OR metodo_pago = 'Efectivo de Caja')
            """, (caja_id,))
            total_gastos = float(cursor.fetchone()['total'])

            # Saldo Teórico Final
            saldo_teorico = (float(sesion_abierta['monto_inicial']) + total_efectivo) - total_gastos

            # --- MOVIMIENTOS ---
            sql_movimientos = """
                (SELECT v.fecha_venta as fecha, vp.monto, vp.metodo_pago, 
                        'Venta #' || COALESCE(v.serie_comprobante, '') || '-' || COALESCE(v.numero_comprobante, 'S/N') as descripcion, 
                        'Ingreso' as flujo, v.id as id, 'Venta' as tipo
                 FROM venta_pagos vp JOIN ventas v ON vp.venta_id = v.id
                 WHERE v.caja_sesion_id = %s AND v.estado_pago != 'Anulado')
                UNION ALL
                (SELECT g.fecha_registro as fecha, (g.monto * -1) as monto, g.metodo_pago, 
                        g.descripcion, 'Egreso' as flujo, g.id as id, 'Gasto' as tipo
                 FROM gastos g WHERE g.caja_sesion_id = %s)
                ORDER BY fecha DESC LIMIT 20
            """
            cursor.execute(sql_movimientos, (caja_id, caja_id))
            movimientos_caja = cursor.fetchall()

            # --- COMISIONES PENDIENTES ---
            cursor.execute("""
                SELECT c.id, c.monto_comision, TO_CHAR(c.fecha_generacion, 'DD/MM HH24:MI') as fecha_fmt,
                       vi.descripcion_item_venta as concepto, v.numero_comprobante,
                       e.nombre_display as colaborador
                FROM comisiones c
                JOIN empleados e ON c.empleado_id = e.id
                JOIN venta_items vi ON c.venta_item_id = vi.id
                JOIN ventas v ON vi.venta_id = v.id
                WHERE c.estado = 'Pendiente' AND v.sucursal_id = %s
                ORDER BY c.fecha_generacion DESC
            """, (sucursal_id,))
            comisiones = cursor.fetchall()

            # --- 🟢 AQUÍ ESTÁ LO QUE FALTABA: PROPINAS PENDIENTES ---
            cursor.execute("""
                SELECT p.id, p.monto, p.metodo_pago, p.fecha_registro, 
                       e.nombre_display
                FROM propinas p
                JOIN empleados e ON p.empleado_id = e.id
                WHERE p.entregado_al_barbero = FALSE
                ORDER BY p.fecha_registro DESC
            """)
            propinas_pendientes = cursor.fetchall()
            
            # --- SERVICIOS EXTRA PENDIENTES (COMISIONES) ---
            cursor.execute("""
                SELECT vi.id, vi.comision_servicio_extra, vi.porcentaje_servicio_extra, 
                       v.fecha_venta, e.nombre_display,
                       vi.descripcion_item_venta
                FROM venta_items vi
                JOIN ventas v ON vi.venta_id = v.id
                JOIN empleados e ON v.empleado_id = e.id
                WHERE vi.es_hora_extra = TRUE 
                  AND vi.entregado_al_colaborador = FALSE 
                  AND v.estado != 'Anulada'
                ORDER BY v.fecha_venta DESC
            """)
            extras_pendientes = cursor.fetchall()

            # --- 🟢 TAMBIÉN FALTABA ESTO: EMPLEADOS (Para el modal) ---
            cursor.execute("SELECT id, nombre_display FROM empleados WHERE activo = TRUE")
            empleados = cursor.fetchall()

            return render_template('caja/cierre.html', 
                                   sesion=sesion_abierta,
                                   total_efectivo=total_efectivo,
                                   total_digital=total_digital,
                                   total_gastos=total_gastos,
                                   saldo_teorico=saldo_teorico,
                                   movimientos=movimientos_caja,
                                   comisiones_pendientes=comisiones,
                                   propinas_pendientes=propinas_pendientes, # <--- Enviamos la lista
                                   extras_pendientes=extras_pendientes, # <--- NEW
                                   empleados=empleados) # <--- Enviamos empleados

    except Exception as e:
        flash(f"Error cargando caja: {e}", "danger")
        return redirect(url_for('main.index'))
    
    
# -------------------------------------------------------------------------
# CERRAR CAJA
# -------------------------------------------------------------------------
@main_bp.route('/finanzas/caja/cerrar/<int:sesion_id>', methods=['POST'])
@login_required
def cerrar_caja(sesion_id):
    db_conn = get_db()
    
    monto_final_real = request.form.get('monto_final_real')
    notas_cierre = request.form.get('notas_cierre')
    destino_remanente = request.form.get('destino_remanente') # 'Caja' o 'Gerencia'
    
    # Lógica de Estado
    estado_entrega = 'En Caja' if destino_remanente == 'Caja' else 'Pendiente'
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Recalcular totales por seguridad
            cursor.execute("SELECT monto_inicial FROM caja_sesiones WHERE id=%s", (sesion_id,))
            res = cursor.fetchone()
            if not res: 
                flash("Sesión no encontrada", "danger")
                return redirect(url_for('main.gestionar_caja'))
            
            monto_inicial = float(res['monto_inicial'])

            cursor.execute("SELECT COALESCE(SUM(vp.monto), 0) as total FROM venta_pagos vp JOIN ventas v ON vp.venta_id = v.id WHERE v.caja_sesion_id = %s AND vp.metodo_pago = 'Efectivo' AND v.estado_pago != 'Anulado'", (sesion_id,))
            total_efectivo = float(cursor.fetchone()['total'])

            cursor.execute("SELECT COALESCE(SUM(vp.monto), 0) as total FROM venta_pagos vp JOIN ventas v ON vp.venta_id = v.id WHERE v.caja_sesion_id = %s AND vp.metodo_pago != 'Efectivo' AND v.estado_pago != 'Anulado'", (sesion_id,))
            total_digital = float(cursor.fetchone()['total'])

            cursor.execute("SELECT COALESCE(SUM(monto), 0) as total FROM gastos WHERE caja_sesion_id = %s AND (metodo_pago = 'Efectivo' OR metodo_pago = 'Efectivo de Caja')", (sesion_id,))
            total_gastos = float(cursor.fetchone()['total'])

            saldo_teorico = (monto_inicial + total_efectivo) - total_gastos
            diferencia = float(monto_final_real) - saldo_teorico

            # Update
            cursor.execute("""
                UPDATE caja_sesiones 
                SET fecha_cierre = CURRENT_TIMESTAMP,
                    estado = 'Cerrada',
                    monto_final_real = %s,
                    total_ventas_efectivo = %s,
                    total_ventas_digital = %s,
                    total_gastos = %s,
                    diferencia = %s,
                    notas_cierre = %s,
                    destino_remanente = %s,
                    estado_entrega = %s
                WHERE id = %s
            """, (monto_final_real, total_efectivo, total_digital, total_gastos, diferencia, notas_cierre, destino_remanente, estado_entrega, sesion_id))
            
            db_conn.commit()
            
            if abs(diferencia) < 0.1:
                flash("Caja cerrada. ¡Cuadre perfecto!", "success")
            elif diferencia > 0:
                flash(f"Caja cerrada con sobrante de S/ {diferencia:.2f}", "info")
            else:
                flash(f"Caja cerrada con faltante de S/ {abs(diferencia):.2f}", "warning")

    except Exception as e:
        db_conn.rollback()
        flash(f"Error al cerrar caja: {e}", "danger")

    return redirect(url_for('main.gestionar_caja'))
# -------------------------------------------------------------------------
# CONFIRMAR RECEPCIÓN (NUEVA RUTA)
# -------------------------------------------------------------------------
@main_bp.route('/finanzas/caja/confirmar_recepcion/<int:sesion_id>', methods=['POST'])
@login_required
def confirmar_recepcion_caja(sesion_id):
    # Validar permisos (solo admin o quien tenga permiso especial)
    es_admin = getattr(current_user, 'rol_nombre', '') == 'Administrador'
    if not es_admin:
        flash("No tienes permiso para confirmar recepciones.", "danger")
        return redirect(url_for('main.listar_historial_caja'))

    db_conn = get_db()
    try:
        with db_conn.cursor() as cursor:
            cursor.execute("""
                UPDATE caja_sesiones 
                SET estado_entrega = 'Conforme' 
                WHERE id = %s AND destino_remanente = 'Gerencia'
            """, (sesion_id,))
            db_conn.commit()
        flash("Recepción de dinero confirmada.", "success")
    except Exception as e:
        db_conn.rollback()
        flash(f"Error: {e}", "danger")
        
    return redirect(url_for('main.listar_historial_caja'))

@main_bp.route('/finanzas/caja/abrir', methods=['POST'])
@login_required

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
        return redirect(url_for('main.gestionar_caja'))

    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Verificar que no haya otra caja abierta para esta sucursal
            cursor.execute("SELECT id FROM caja_sesiones WHERE sucursal_id = %s AND estado = 'Abierta'", (sucursal_id,))
            if cursor.fetchone():
                flash(f"Ya existe una sesión de caja abierta para esta sucursal.", "warning")
                return redirect(url_for('main.gestionar_caja'))
            
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

    except Exception as err:
        db_conn.rollback()
        flash(f"Error al abrir la caja: {err}", "danger")
        current_app.logger.error(f"Error en abrir_caja: {err}")

    return redirect(url_for('main.gestionar_caja'))

# -------------------------------------------------------------------------
# HISTORIAL DE CAJA Y CONFIRMACIÓN
# -------------------------------------------------------------------------
@main_bp.route('/finanzas/caja/historial')
@login_required
def listar_historial_caja():
    """Muestra la lista de todas las sesiones de caja pasadas."""
    db_conn = get_db()
    sucursal_id = session.get('sucursal_id')
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            
            # LÓGICA INTELIGENTE:
            # 1. Si es Administrador: Ver historial de TODAS las sucursales.
            # 2. Si es Cajero/Otro: Ver solo historial de SU sucursal actual.
            
            es_admin = getattr(current_user, 'rol_nombre', '') == 'Administrador'
            
            if es_admin:
                # Consulta GLOBAL (sin filtro de sucursal)
                sql = """
                    SELECT cs.*, 
                           e.nombre_display as cajero_nombre,
                           s.nombre as sucursal_nombre, -- Agregamos el nombre de la sede
                           TO_CHAR(cs.fecha_apertura, 'DD/MM/YYYY HH24:MI') as inicio_fmt,
                           TO_CHAR(cs.fecha_cierre, 'DD/MM/YYYY HH24:MI') as fin_fmt
                    FROM caja_sesiones cs
                    JOIN empleados e ON cs.usuario_id = e.id
                    LEFT JOIN sucursales s ON cs.sucursal_id = s.id
                    ORDER BY cs.fecha_apertura DESC
                    LIMIT 100
                """
                cursor.execute(sql)
            
            elif sucursal_id:
                # Consulta FILTRADA por sucursal
                sql = """
                    SELECT cs.*, 
                           e.nombre_display as cajero_nombre,
                           s.nombre as sucursal_nombre,
                           TO_CHAR(cs.fecha_apertura, 'DD/MM/YYYY HH24:MI') as inicio_fmt,
                           TO_CHAR(cs.fecha_cierre, 'DD/MM/YYYY HH24:MI') as fin_fmt
                    FROM caja_sesiones cs
                    JOIN empleados e ON cs.usuario_id = e.id
                    LEFT JOIN sucursales s ON cs.sucursal_id = s.id
                    WHERE cs.sucursal_id = %s
                    ORDER BY cs.fecha_apertura DESC
                    LIMIT 50
                """
                cursor.execute(sql, (sucursal_id,))
            else:
                # Si no es admin y no tiene sucursal, no ve nada
                flash("Selecciona una sucursal para ver el historial.", "warning")
                return redirect(url_for('main.index'))

            sesiones = cursor.fetchall()
            
        return render_template('caja/historial.html', sesiones=sesiones)
        
    except Exception as e:
        flash(f"Error al cargar historial: {e}", "danger")
        current_app.logger.error(f"Error historial caja: {e}")
        return redirect(url_for('main.gestionar_caja'))

@main_bp.route('/finanzas/caja/pagar-comision/<int:comision_id>', methods=['POST'])
@login_required
def pagar_comision_caja(comision_id):
    """
    Registra el pago de una comisión específica usando dinero de la caja abierta.
    """
    # VERIFICACIÓN DE PERMISOS: Admin, Cajera o Cajero
    rol = getattr(current_user, 'rol_nombre', '')
    if rol != 'Administrador' and rol not in ['Cajera', 'Cajero']:
        flash("No tienes permiso para realizar esta acción.", "danger")
        return redirect(url_for('main.gestionar_caja'))

    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Verificar que exista caja abierta
            sucursal_id = session.get('sucursal_id')
            cursor.execute("SELECT id FROM caja_sesiones WHERE sucursal_id = %s AND usuario_id = %s AND estado = 'Abierta'", (sucursal_id, current_user.id))
            caja = cursor.fetchone()
            
            if not caja:
                flash("No hay caja abierta para registrar este pago.", "warning")
                return redirect(url_for('main.gestionar_caja', sucursal_id=sucursal_id))

            # 2. Obtener datos de la comisión
            cursor.execute("SELECT monto_comision, empleado_id FROM comisiones WHERE id = %s", (comision_id,))
            comision = cursor.fetchone()

            # 3. Registrar el GASTO en la caja (Salida de dinero)
            # Primero buscamos o creamos la categoría "Pago de Comisiones"
            cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Pago de Comisiones'")
            cat = cursor.fetchone()
            if not cat:
                cursor.execute("INSERT INTO categorias_gastos (nombre) VALUES ('Pago de Comisiones') RETURNING id")
                cat_id = cursor.fetchone()['id']
            else:
                cat_id = cat['id']

            cursor.execute("""
                INSERT INTO gastos (sucursal_id, categoria_gasto_id, caja_sesion_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id)
                VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, 'Efectivo', %s)
            """, (sucursal_id, cat_id, caja['id'], f"Pago comisión ID {comision_id}", comision['monto_comision'], current_user.id))

            # 4. Marcar comisión como PAGADA
            cursor.execute("""
                UPDATE comisiones 
                SET estado = 'Pagada', fecha_pago = CURRENT_TIMESTAMP, pago_caja_sesion_id = %s 
                WHERE id = %s
            """, (caja['id'], comision_id))

            db_conn.commit()
            flash(f"Comisión de S/ {comision['monto_comision']} pagada correctamente.", "success")

    except Exception as e:
        db_conn.rollback()
        flash(f"Error al pagar comisión: {e}", "danger")

    return redirect(url_for('main.gestionar_caja', sucursal_id=sucursal_id))

@main_bp.route('/finanzas/caja/pagar-extra/<int:item_id>', methods=['POST'])
@login_required
def pagar_extra_caja(item_id):
    # VERIFICACIÓN DE PERMISOS: Admin, Cajera o Cajero
    rol = getattr(current_user, 'rol_nombre', '')
    if rol != 'Administrador' and rol not in ['Cajera', 'Cajero']:
        flash("No tienes permiso para realizar esta acción.", "danger")
        return redirect(url_for('main.gestionar_caja'))

    db_conn = get_db()
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Verificar Caja Abierta
            sucursal_id = session.get('sucursal_id')
            cursor.execute("SELECT id FROM caja_sesiones WHERE sucursal_id = %s AND usuario_id = %s AND estado = 'Abierta'", (sucursal_id, current_user.id))
            caja = cursor.fetchone()
            if not caja:
                 flash("No hay caja abierta.", "warning")
                 return redirect(url_for('main.gestionar_caja'))

            # 2. Obtener Datos del Item
            cursor.execute("SELECT comision_servicio_extra, descripcion_item_venta FROM venta_items WHERE id = %s", (item_id,))
            item = cursor.fetchone()
            monto = float(item['comision_servicio_extra'] or 0)

            # 3. Registrar Gasto
            cursor.execute("SELECT id FROM categorias_gastos WHERE nombre = 'Pago Servicios Extra'")
            cat = cursor.fetchone()
            if not cat:
                cursor.execute("INSERT INTO categorias_gastos (nombre) VALUES ('Pago Servicios Extra') RETURNING id")
                cat_id = cursor.fetchone()['id']
            else:
                cat_id = cat['id']

            cursor.execute("""
                INSERT INTO gastos (sucursal_id, categoria_gasto_id, caja_sesion_id, fecha, descripcion, monto, metodo_pago, registrado_por_colaborador_id)
                VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, 'Efectivo', %s)
            """, (sucursal_id, cat_id, caja['id'], f"Pago Extra: {item['descripcion_item_venta']}", monto, current_user.id))

            # 4. Actualizar estado
            cursor.execute("UPDATE venta_items SET entregado_al_colaborador = TRUE WHERE id = %s", (item_id,))
            
            db_conn.commit()
            flash(f"Pago de extra (S/ {monto:.2f}) registrado.", "success")
            
    except Exception as e:
        db_conn.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(url_for('main.gestionar_caja'))

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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT puntos_fidelidad FROM clientes WHERE id = %s", (cliente_id,))
            cliente = cursor.fetchone()
            
            if cliente:
                # Obtener el valor, si es nulo (None), convertirlo a 0
                puntos = cliente.get('puntos_fidelidad') or 0
                # Devolver siempre el JSON con la clave que el JavaScript espera
                return jsonify({"puntos_disponibles": puntos})
            else:
                return jsonify({"error": "Cliente no encontrado."}), 404

    except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
    except Exception as err:
        flash(f"Error al cargar sucursales: {err}", "danger")

    resultados = None # Inicializamos los resultados como nulos

    # Si se enviaron los filtros, procesar los datos
    if fecha_inicio_str and fecha_fin_str and sucursal_id_str:
        try:
            sucursal_id = int(sucursal_id_str)
            
            # Asegurarse de que el rango de fechas cubra el día completo
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
            
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

        except (ValueError, Exception) as e:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores_activos = cursor.fetchall()
    except Exception as err:
        flash(f"Error al cargar la lista de colaboradores: {err}", "danger")

    resultados = None
    # Si se enviaron todos los filtros, generar el reporte
    if colaborador_id and anio and mes:
        try:
            # Primero, verificar si la liquidación para este período ya fue pagada
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

                with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    # 1. Obtener datos base del colaborador
                    cursor.execute("SELECT * FROM empleados WHERE id = %s", (colaborador_id,))
                    colaborador_seleccionado = cursor.fetchone()
                    if not colaborador_seleccionado: raise ValueError("Colaborador no encontrado.")
                    sueldo_base = float(colaborador_seleccionado.get('sueldo_base', 0.0))

                    cursor.execute("SELECT monto_cuota FROM cuotas_mensuales WHERE colaborador_id = %s AND anio = %s AND mes = %s", (colaborador_id, anio, mes))
                    cuota_obj = cursor.fetchone()
                    monto_cuota = float(cuota_obj['monto_cuota']) if cuota_obj else 0.0

                    # 2. Calcular Métricas de Rendimiento del Mes
                    cursor.execute("SELECT SUM(vi.valor_produccion) as total FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id WHERE v.empleado_id = %s AND v.estado_pago != 'Anulado' AND DATE(v.fecha_venta) BETWEEN %s AND %s AND vi.servicio_id IS NOT NULL AND vi.es_hora_extra = FALSE", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
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
                    cursor.execute("SELECT *, TO_CHAR(fecha_generacion, 'DD/MM/YYYY') as fecha_corta FROM comisiones WHERE colaborador_id = %s AND estado = 'Pendiente' AND DATE(fecha_generacion) BETWEEN %s AND %s", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
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
        cursor = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT *, TO_CHAR(fecha_inicio, 'DD/MM/YYYY') as f_inicio, TO_CHAR(fecha_fin, 'DD/MM/YYYY') as f_fin FROM campanas ORDER BY fecha_inicio DESC")
        lista_de_campanas = cursor.fetchall()
        cursor.close()
    except Exception as err:
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
            except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombres, apellidos FROM empleados WHERE activo = TRUE ORDER BY apellidos, nombres")
            colaboradores = cursor.fetchall()
    except Exception as err:
        flash(f"Error al cargar datos para los filtros: {err}", "danger")

    resultados = None
    if colaborador_id and sucursal_id and fecha_inicio and fecha_fin:
        try:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Consulta para el detalle de SERVICIOS
                sql_servicios = """
                    SELECT 
                        v.fecha_venta, 
                        COALESCE(CONCAT(cl.razon_social_nombres, ' ', cl.apellidos), 'Cliente Varios') AS cliente_nombre,
                        s.nombre as servicio_nombre, 
                        vi.precio_unitario_venta, 
                        vi.subtotal_item_neto as valor_produccion,
                        vi.usado_como_beneficio,
                        ca.nombre as campana_nombre, 
                        vi.es_hora_extra
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
                        vi.subtotal_item_neto as valor_produccion,
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
                
                # Cálculos para el resumen usando 'valor_produccion' (que ahora es el subtotal neto correjido)
                total_produccion_servicios_regular = sum(float(s['valor_produccion']) for s in servicios_vendidos if not s.get('es_hora_extra'))
                total_produccion_servicios_extra = sum(float(s['valor_produccion']) for s in servicios_vendidos if s.get('es_hora_extra'))
                
                total_produccion_servicios = total_produccion_servicios_regular + total_produccion_servicios_extra
                
                total_produccion_productos = sum(float(p['valor_produccion']) for p in productos_vendidos)
                
                # Las comisiones se calculan aparte, no cambian
                total_comisiones_productos = sum(float(p['monto_comision']) for p in productos_vendidos if p.get('monto_comision'))
                cursor.execute("""SELECT SUM(c.monto_comision) as total FROM comisiones c JOIN venta_items vi ON c.venta_item_id = vi.id JOIN ventas v ON vi.venta_id = v.id WHERE c.empleado_id = %s AND vi.servicio_id IS NOT NULL AND DATE(c.fecha_generacion) BETWEEN %s AND %s""", (colaborador_id, fecha_inicio, fecha_fin))
                comisiones_servicios = cursor.fetchone()
                total_comisiones_servicios = float(comisiones_servicios['total']) if comisiones_servicios and comisiones_servicios['total'] else 0.0
                total_comisiones_generadas = total_comisiones_productos + total_comisiones_servicios

                # --- NUEVO: Propinas y Fidelidad ---
                cursor.execute("SELECT * FROM propinas WHERE empleado_id = %s AND DATE(fecha_registro) BETWEEN %s AND %s ORDER BY fecha_registro DESC", (colaborador_id, fecha_inicio, fecha_fin))
                propinas = cursor.fetchall()
                total_propinas = sum(float(p['monto']) for p in propinas)

                cursor.execute("SELECT * FROM ajustes_pago WHERE empleado_id = %s AND tipo ILIKE '%%Fidelidad%%' AND DATE(fecha) BETWEEN %s AND %s ORDER BY fecha DESC", (colaborador_id, fecha_inicio, fecha_fin))
                ajustes_fidelidad = cursor.fetchall()
                total_fidelidad = sum(abs(float(a['monto'])) for a in ajustes_fidelidad)

                resultados = {
                    "servicios_vendidos": servicios_vendidos, 
                    "productos_vendidos": productos_vendidos,
                    "propinas": propinas, # NEW
                    "ajustes_fidelidad": ajustes_fidelidad, # NEW
                    
                    "total_produccion_servicios_regular": total_produccion_servicios_regular,
                    "total_produccion_servicios_extra": total_produccion_servicios_extra,
                    "total_produccion_servicios": total_produccion_servicios,
                    "total_produccion_productos": total_produccion_productos,
                    "total_comisiones": total_comisiones_generadas,
                    "total_propinas": total_propinas, # NEW
                    "total_fidelidad": total_fidelidad # NEW
                }
                
        except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Obtener nombre del colaborador para el nombre del archivo
            cursor.execute("SELECT nombres, apellidos FROM empleados WHERE id = %s", (colaborador_id,))
            colaborador = cursor.fetchone()
            nombre_colaborador = f"{colaborador['nombres']} {colaborador['apellidos']}"

            # Ejecutar las mismas consultas que en el reporte en pantalla
            # Consulta para SERVICIOS
            sql_servicios = """SELECT v.fecha_venta, cl.nombres as cliente_nombres, cl.apellidos as cliente_apellidos, s.nombre as servicio_nombre, vi.precio_unitario_venta, ca.nombre as campana_nombre, vi.es_hora_extra FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id JOIN servicios s ON vi.servicio_id = s.id LEFT JOIN clientes cl ON v.cliente_id = cl.id LEFT JOIN campanas ca ON v.campana_id = ca.id WHERE v.empleado_id = %s AND v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s ORDER BY v.fecha_venta DESC"""
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
            df_servicios.rename(columns={'fecha_venta': 'Fecha', 'cliente_nombres': 'Nombres Cliente', 'cliente_apellidos': 'Apellidos Cliente', 'servicio_nombre': 'Servicio', 'precio_unitario_venta': 'Precio', 'campana_nombre': 'Campaña', 'es_hora_extra': 'Es Extra'}, inplace=True)
        if not df_productos.empty:
            df_productos.rename(columns={'fecha_venta': 'Fecha', 'cliente_nombres': 'Nombres Cliente', 'cliente_apellidos': 'Apellidos Cliente', 'producto_nombre': 'Producto', 'marca_nombre': 'Marca', 'cantidad': 'Cantidad', 'precio_unitario_venta': 'P. Venta Unit.', 'subtotal_item_neto': 'Subtotal', 'monto_comision': 'Comisión'}, inplace=True)

        # Crear un archivo Excel en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_servicios.to_excel(writer, sheet_name='Servicios Realizados', index=False)
            df_productos.to_excel(writer, sheet_name='Productos Vendidos', index=False)
        output.seek(0)
        
        # Preparar la respuesta para 
        # el archivo
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales = cursor.fetchall()
    except Exception as err:
        flash(f"Error al cargar sucursales: {err}", "danger")

    resultados = []
    totales_generales = {}
    if sucursal_id and fecha_inicio and fecha_fin:
        try:
            with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Esta consulta obtiene la producción y comisiones agrupadas por colaborador
                sql = """
                    SELECT
                        e.id as colaborador_id,
                        e.nombre_display AS colaborador_nombre,
                        SUM(CASE WHEN vi.servicio_id IS NOT NULL AND vi.es_hora_extra = FALSE THEN vi.subtotal_item_neto ELSE 0 END) as produccion_servicios_regular,
                        SUM(CASE WHEN vi.servicio_id IS NOT NULL AND vi.es_hora_extra = TRUE THEN vi.subtotal_item_neto ELSE 0 END) as produccion_servicios_extra,
                        SUM(CASE WHEN vi.producto_id IS NOT NULL THEN vi.subtotal_item_neto ELSE 0 END) as produccion_productos,
                        (SELECT SUM(c.monto_comision) FROM comisiones c JOIN venta_items vi_c ON c.venta_item_id = vi_c.id JOIN ventas v_c ON vi_c.venta_id = v_c.id WHERE v_c.empleado_id = e.id AND DATE(v_c.fecha_venta) BETWEEN %s AND %s) as total_comisiones,
                        (SELECT COALESCE(SUM(p.monto), 0) FROM propinas p WHERE p.empleado_id = e.id AND DATE(p.fecha_registro) BETWEEN %s AND %s) as total_propinas,
                        (SELECT COALESCE(ABS(SUM(a.monto)), 0) FROM ajustes_pago a WHERE a.empleado_id = e.id AND a.tipo ILIKE '%%Fidelidad%%' AND DATE(a.fecha) BETWEEN %s AND %s) as total_fidelidad
                    FROM ventas v
                    JOIN empleados e ON v.empleado_id = e.id
                    JOIN venta_items vi ON v.id = vi.venta_id
                    WHERE v.sucursal_id = %s AND DATE(v.fecha_venta) BETWEEN %s AND %s
                      AND v.estado_pago != 'Anulado'
                    GROUP BY e.id, e.nombre_display
                    ORDER BY colaborador_nombre;
                """
                cursor.execute(sql, (fecha_inicio, fecha_fin, fecha_inicio, fecha_fin, fecha_inicio, fecha_fin, sucursal_id, fecha_inicio, fecha_fin))
                resultados = cursor.fetchall()
                
                # Calcular los totales generales para el resumen
                if resultados:
                    totales_generales = {
                        'total_servicios_regular': sum(float(r['produccion_servicios_regular']) for r in resultados),
                        'total_servicios_extra': sum(float(r['produccion_servicios_extra']) for r in resultados),
                        'total_productos': sum(float(r['produccion_productos']) for r in resultados),
                        'total_comisiones': sum(float(r['total_comisiones'] or 0) for r in resultados),
                        'total_propinas': sum(float(r['total_propinas'] or 0) for r in resultados),
                        'total_fidelidad': sum(float(r['total_fidelidad'] or 0) for r in resultados)
                    }
                    # Total Meta = Solo Regular
                    totales_generales['total_meta'] = totales_generales['total_servicios_regular']

        except Exception as err:
            flash(f"Error al generar el reporte de producción: {err}", "danger")

    return render_template('reportes/reporte_produccion_general.html',
                           titulo_pagina="Reporte de Producción General",
                           sucursales=sucursales,
                           filtros=request.args,
                           resultados=resultados,
                           totales=totales_generales)


# --- RUTAS PARA ROLES ---

@main_bp.route('/configuracion/roles')
@login_required
@admin_required # Solo un administrador puede gestionar roles
def listar_roles():
    """
    Muestra la lista de todos los roles de usuario definidos en el sistema.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre, descripcion FROM roles ORDER BY nombre")
            lista_de_roles = cursor.fetchall()
    except Exception as err:
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
            except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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

    except Exception as err:
        db_conn.rollback()
        flash(f"Error de base de datos al guardar los permisos: {err}", "danger")

    return redirect(url_for('main.listar_roles'))


# --- RUTAS PARA COMANDA ---


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
                                                 cantidad, precio_unitario_venta, subtotal_item_bruto, subtotal_item_neto, es_hora_extra, notas_item)
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
                        bool(item.get('es_hora_extra', False)),
                        item.get('notas_item') # Guardar la nota del estilo
                    )
                    cursor.execute(sql_item, val_item)
            
            db_conn.commit()
            flash(f"Comanda #{venta_id} enviada a caja exitosamente.", "success")
            return redirect(url_for('main.nueva_comanda'))

        except (ValueError, Exception, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"No se pudo enviar la comanda. Error: {str(e)}", "warning")
            current_app.logger.error(f"Error procesando comanda: {e}")
            return redirect(url_for('main.nueva_comanda'))

    # --- Lógica GET (para mostrar el formulario) ---
    listas_para_form = { 'clientes': [], 'servicios': [], 'productos': [], 'estilos_catalogo': [] }
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
    
    except Exception as err:
        flash(f"Error al cargar las comandas pendientes: {err}", "danger")
        current_app.logger.error(f"Error en listar_comandas_pendientes: {err}")

    return render_template('ventas/comandas_pendientes.html',
                           titulo_pagina="Comandas Pendientes de Cobro",
                           sucursales=sucursales,
                           sucursal_seleccionada_id=sucursal_id_seleccionada,
                           comandas=comandas_pendientes)
    
# --- RUTAS PARA BONOS ---

@main_bp.route('/configuracion/bonos')
@login_required
@admin_required
def listar_bonos():
    """
    Muestra la lista de todos los bonos e incentivos configurados.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM bonos ORDER BY nombre")
            lista_de_bonos = cursor.fetchall()
    except Exception as err:
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
            except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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
    except (ValueError, Exception) as e:
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
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
        db.rollback()
        flash(f"Error al eliminar la regla: {err}", "danger")

    if bono_id_para_redirigir:
        return redirect(url_for('main.gestionar_reglas_bono', bono_id=bono_id_para_redirigir))
    else:
        # Si algo falla, volver a la lista general de bonos
        return redirect(url_for('main.listar_bonos'))

# --- RUTAS PARA MEMBRESIAS ---


@main_bp.route('/configuracion/membresias')
@login_required
@admin_required
def listar_planes_membresia():
    """
    Muestra la lista de todos los planes de membresía definidos.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM membresia_planes ORDER BY nombre")
            planes = cursor.fetchall()
    except Exception as err:
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

        except (ValueError, Exception, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"Error al crear el plan: {e}", "danger")
    
    # Lógica GET (sin cambios)
    servicios_disponibles = []
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

        except (ValueError, Exception, Exception) as e:
            if db_conn and db_conn.in_transaction: db_conn.rollback()
            flash(f"Error al actualizar el plan: {e}", "danger")
            # En caso de error, volver a la misma página de edición
            return redirect(url_for('main.editar_plan_membresia', plan_id=plan_id))

    # --- Lógica GET (para mostrar el formulario con datos existentes) ---
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
        flash(f"Error al acceder a las membresías de clientes: {err}", "danger")
        current_app.logger.error(f"Error en listar_cliente_membresias: {err}")

    return render_template('membresias/lista_cliente_membresias.html',
                           membresias=lista_membresias,
                           filtro_actual=filtro_estado,
                           titulo_pagina="Membresías de Clientes")


@main_bp.route('/configuracion/membresias/toggle-activo/<int:plan_id>')
@login_required
@admin_required
def toggle_activo_plan_membresia(plan_id):
    """
    Activa o desactiva un plan de membresía.
    """
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

    except Exception as err:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
            
            cursor.execute("SELECT SUM(vi.valor_produccion) as total FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id WHERE v.empleado_id = %s AND v.estado_pago != 'Anulado' AND DATE(v.fecha_venta) BETWEEN %s AND %s AND (vi.producto_id IS NOT NULL OR (vi.servicio_id IS NOT NULL AND vi.es_hora_extra = FALSE))", (colaborador_id, fecha_inicio_periodo, fecha_fin_periodo))
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
                cursor.execute(f"UPDATE comisiones SET estado = 'Pagada', fecha_pago = CURRENT_TIMESTAMP WHERE id IN ({format_strings_com})", tuple(comisiones_ids))
            if ajustes_ids:
                cursor.execute(f"UPDATE ajustes_pago SET estado = 'Aplicado en Liquidación' WHERE id IN ({format_strings_aj})", tuple(ajustes_ids))

            # 5. Guardar el registro histórico en 'liquidaciones'
            sql_liquidacion = "INSERT INTO liquidaciones (colaborador_id, anio, mes, fecha_pago, monto_sueldo_base, monto_bono_produccion, monto_total_comisiones, monto_total_otros_ingresos, monto_total_descuentos, monto_liquido_pagado, gasto_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            val_liquidacion = (colaborador_id, anio, mes, datetime.now(), sueldo_base, bono_produccion, total_comisiones, total_otros_bonos, total_descuentos, liquido_a_pagar_calculado, gasto_id)
            cursor.execute(sql_liquidacion, val_liquidacion)
        
        db_conn.commit()
        flash(f"Liquidación para el período {mes}/{anio} registrada y marcada como pagada exitosamente.", "success")

    except (ValueError, Exception, Exception) as e:
        if db_conn and db_conn.in_transaction: db_conn.rollback()
        flash(f"No se pudo registrar el pago de la liquidación. Error: {str(e)}", "danger")
        current_app.logger.error(f"Error en pagar_liquidacion: {e}")

    return redirect(redirect_url)

# En app/routes.py

import pandas as pd # Asegúrate de importar pandas al inicio del archivo
from werkzeug.utils import secure_filename

@main_bp.route('/clientes/importar', methods=['GET', 'POST'])
@login_required
@admin_required
def importar_clientes():
    resultados = {'insertados': 0, 'errores': []}
    procesado = False

    if request.method == 'POST':
        # --- 1. VERIFICACIONES ---
        sucursal_id = session.get('sucursal_id') or getattr(current_user, 'sucursal_id', None)
        
        if not sucursal_id:
            flash('Seleccione una sucursal de trabajo antes de importar.', 'danger')
            return redirect(request.url)

        if 'archivo' not in request.files or not request.files['archivo'].filename:
            flash('No se seleccionó ningún archivo.', 'danger')
            return redirect(request.url)
        
        file = request.files['archivo']
        if not file.filename.endswith(('.xlsx', '.xls')):
            flash('Formato inválido. Solo .xlsx y .xls.', 'danger')
            return redirect(request.url)

        # --- 2. PROCESAMIENTO ---
        db = get_db()
        cursor = None
        procesado = True

        try:
            # Leemos el Excel
            df = pd.read_excel(file)
            df.columns = [str(c).strip().upper() for c in df.columns]

            required_cols = ['RAZONSOCIALNOMBRES', 'TELEFONO']
            if not all(col in df.columns for col in required_cols):
                flash(f'Faltan columnas obligatorias: {", ".join(required_cols)}.', 'danger')
                return render_template('clientes/importar_clientes.html', titulo_pagina="Importar Clientes", resultados=resultados, procesado=procesado)

            db.rollback()
            cursor = db.cursor()

            # Cargamos datos para validaciones
            cursor.execute("SELECT numero_documento FROM clientes WHERE numero_documento IS NOT NULL")
            docs_existentes = {str(row[0]).strip() for row in cursor.fetchall()}

            # Validación de "Cliente Único" (Nombre + Teléfono)
            # Permite que un mismo teléfono se repita si el nombre es diferente (ej: Madre e hijos)
            cursor.execute("SELECT LOWER(razon_social_nombres), telefono FROM clientes")
            # Creamos un set de tuplas para búsqueda rápida: {('juan perez', '999123'), ...}
            clientes_registrados = {(row[0], str(row[1]).strip()) for row in cursor.fetchall() if row[0] and row[1]}

            lista_para_insertar = []
            
            # Helpers
            def clean_value(v): return str(v).strip() if pd.notna(v) and str(v).strip().lower() not in ['nan', ''] else None
            def parse_date(v): return pd.to_datetime(v).date() if pd.notna(v) else None

            for index, row in df.iterrows():
                try:
                    nombre_raw = str(row.get('RAZONSOCIALNOMBRES', '')).strip()
                    
                    # 🟢 CORRECCIÓN DEL TELÉFONO (.0)
                    raw_tel = row.get('TELEFONO', '')
                    telefono = str(raw_tel).strip()
                    if telefono.endswith('.0'):
                        telefono = telefono[:-2] # Corta los últimos 2 caracteres (.0)
                    
                    num_doc = clean_value(row.get('NUMERODOCUMENTO'))

                    # 1. Validación básica
                    if not nombre_raw or not telefono or telefono == 'nan':
                        resultados['errores'].append(f"Fila {index + 2}: Falta Nombre o Teléfono.")
                        continue

                    # 2. Validación de Documento único
                    if num_doc and num_doc in docs_existentes:
                        resultados['errores'].append(f"Fila {index + 2}: Documento '{num_doc}' ya existe.")
                        continue
                    
                    # 3. Validación: ¿Existe ya esa persona con ese número?
                    clave_unica = (nombre_raw.lower(), telefono)
                    
                    if clave_unica in clientes_registrados:
                        resultados['errores'].append(f"Fila {index + 2}: El cliente '{nombre_raw}' ya está registrado con este teléfono.")
                        continue

                    # Preparar fila
                    fila_datos = (
                        nombre_raw, 
                        telefono, 
                        sucursal_id,
                        clean_value(row.get('APELLIDOS')), 
                        clean_value(row.get('TIPODOCUMENTO')), 
                        num_doc,
                        clean_value(row.get('EMAIL')), 
                        clean_value(row.get('DIRECCION')),
                        parse_date(row.get('FECHANACIMIENTO')), 
                        parse_date(row.get('FECHAREGISTRO')) or datetime.now().date(),
                        clean_value(row.get('GENERO')) or 'Masculino',
                        clean_value(row.get('PREFERENCIASERVICIO')) or 'Barberia'
                    )
                    lista_para_insertar.append(fila_datos)
                    
                    # Actualizar sets locales para evitar duplicados dentro del mismo Excel
                    if num_doc: docs_existentes.add(num_doc)
                    clientes_registrados.add(clave_unica)

                except Exception as row_e:
                    resultados['errores'].append(f"Fila {index + 2}: Error datos. ({str(row_e)})")

            # 4. INSERT MASIVO
            if lista_para_insertar:
                sql = """
                    INSERT INTO clientes (
                        razon_social_nombres, telefono, sucursal_id, apellidos, tipo_documento, numero_documento,
                        email, direccion, fecha_nacimiento, fecha_registro, genero, preferencia_servicio
                    ) VALUES %s
                """
                execute_values(cursor, sql, lista_para_insertar)
                resultados['insertados'] = len(lista_para_insertar)

            db.commit()
            
            if resultados['insertados'] > 0:
                flash(f"Se importaron {resultados['insertados']} clientes correctamente.", 'success')
            elif resultados['errores']:
                flash(f"Se encontraron {len(resultados['errores'])} errores (ver detalle abajo).", 'warning')
            else:
                flash("No se encontraron clientes nuevos para importar.", "info")

        except (Exception, psycopg2.Error) as e:
            if db: db.rollback()
            flash(f'Error crítico: {str(e)}', 'danger')
            current_app.logger.error(f"Error importación: {e}", exc_info=True)
        finally:
            if cursor: cursor.close()
    
    return render_template('clientes/importar_clientes.html', titulo_pagina="Importar Clientes", resultados=resultados, procesado=procesado)


@main_bp.route('/configuracion/facturacion', methods=['GET', 'POST'])
@login_required
@admin_required
def configurar_facturacion():
    instance_path = current_app.instance_path
    certs_path = os.path.join(instance_path, 'certs')
    os.makedirs(certs_path, exist_ok=True)
    db_conn = get_db()

    if request.method == 'POST':
        try:
            # Guardar el Certificado
            if 'certificado_digital' in request.files:
                archivo = request.files['certificado_digital']
                if archivo and archivo.filename != '':
                    nombre_seguro = secure_filename("certificado_sunat.pfx")
                    archivo.save(os.path.join(certs_path, nombre_seguro))
                    flash('Certificado digital guardado exitosamente.', 'success')

            # Guardar configuración en la base de datos
            with db_conn.cursor() as cursor:
                sql_update = """
                    UPDATE configuracion_sistema SET
                        ruc_empresa = %s,
                        razon_social = %s,
                        direccion_fiscal = %s,
                        ubigeo = %s,
                        clave_certificado = %s,
                        usuario_sol = %s,
                        clave_sol = %s
                    WHERE id = 1
                """
                val = (
                    request.form.get('ruc_empresa'),
                    request.form.get('razon_social'),
                    request.form.get('direccion_fiscal'),
                    request.form.get('ubigeo'),
                    request.form.get('clave_certificado'),
                    request.form.get('usuario_sol'),
                    request.form.get('clave_sol')
                )
                cursor.execute(sql_update, val)
            db_conn.commit()
            
            # Opcional: Eliminar el archivo JSON antiguo si existe para evitar confusiones
            credentials_file_path = os.path.join(instance_path, 'sunat_credentials.json')
            if os.path.exists(credentials_file_path):
                os.remove(credentials_file_path)

            flash('Configuración de facturación guardada en la base de datos exitosamente.', 'success')
            return redirect(url_for('main.configurar_facturacion'))
        except Exception as e:
            db_conn.rollback()
            flash(f"Ocurrió un error al guardar la configuración: {e}", 'danger')

    # Lógica GET
    certificado_existente = os.path.exists(os.path.join(certs_path, "certificado_sunat.pfx"))
    config_existente = {}
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM configuracion_sistema WHERE id = 1")
            config_existente = cursor.fetchone()
    except Exception as e:
        flash(f"Error al cargar la configuración existente: {e}", "warning")

    return render_template('configuracion/form_facturacion.html',
                           titulo_pagina="Configuración de Facturación Electrónica",
                           certificado_existente=certificado_existente,
                           credenciales=config_existente)


def _generar_y_firmar_xml(venta_id):
    """
    Función interna que genera y firma el XML para una venta.
    Devuelve el string del XML firmado y el nombre base del archivo.
    """
    db_conn = get_db()
    
    # --- 1. Cargar Datos de BD ---
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        sql_venta = """
            SELECT v.*, s.nombre AS sucursal_nombre 
            FROM ventas v JOIN sucursales s ON v.sucursal_id = s.id 
            WHERE v.id = %s
        """
        cursor.execute(sql_venta, (venta_id,))
        venta = cursor.fetchone()
        if not venta: raise ValueError("Venta no encontrada.")
        
        # Cliente
        if venta.get('cliente_facturacion_id'):
            cursor.execute("SELECT * FROM clientes WHERE id = %s", (venta['cliente_facturacion_id'],))
            cliente = cursor.fetchone()
        else:
            # Cliente genérico 'VARIOS' si no hay datos específicos
            cliente = {'tipo_documento': 'Otro', 'numero_documento': '00000000', 'razon_social_nombres': 'CLIENTES VARIOS', 'apellidos': ''}

        # Ítems
        cursor.execute("SELECT * FROM venta_items WHERE venta_id = %s", (venta_id,))
        items = cursor.fetchall()
        if not items: raise ValueError("La venta no tiene ítems.")

        # Configuración de Empresa
        cursor.execute("SELECT ruc_empresa, razon_social, clave_certificado FROM configuracion_sistema WHERE id = 1")
        config_empresa = cursor.fetchone()
        if not config_empresa: raise ValueError("Falta configuración de empresa.")

    # --- 2. Cargar Certificado ---
    instance_path = current_app.instance_path
    certs_path = os.path.join(instance_path, 'certs', 'certificado_sunat.pfx')
    
    if not os.path.exists(certs_path):
        raise ValueError("No se encuentra el archivo certificado_sunat.pfx")
    
    clave_cert = config_empresa.get('clave_certificado')
    if not clave_cert: raise ValueError("No hay clave de certificado en la BD.")

    with open(certs_path, 'rb') as pfx_file:
        pfx_data = pfx_file.read()
    
    # Cargar llaves
    private_key, public_cert, additional_certs = pkcs12.load_key_and_certificates(
        pfx_data, 
        clave_cert.encode('utf-8')
    )

    # --- 3. Construcción del XML (UBL 2.1) ---
    NS_MAP = {
        None: "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
        "ds": "http://www.w3.org/2000/09/xmldsig#"
    }
    
    invoice = ET.Element("Invoice", nsmap=NS_MAP)
    
    # Extensión para la Firma
    ubl_extensions = ET.SubElement(invoice, ET.QName(NS_MAP["ext"], "UBLExtensions"))
    ubl_extension = ET.SubElement(ubl_extensions, ET.QName(NS_MAP["ext"], "UBLExtension"))
    ext_content = ET.SubElement(ubl_extension, ET.QName(NS_MAP["ext"], "ExtensionContent"))

    # Datos Generales
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "UBLVersionID")).text = "2.1"
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "CustomizationID")).text = "2.0"
    
    serie = venta.get('serie_comprobante', 'B001')
    numero = str(venta.get('numero_comprobante', 1)).zfill(8)
    comprobante_id = f"{serie}-{numero}"
    
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "ID")).text = comprobante_id
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "IssueDate")).text = venta['fecha_venta'].strftime('%Y-%m-%d')
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "IssueTime")).text = venta['fecha_venta'].strftime('%H:%M:%S')
    
    # Tipo Comprobante (01=Factura, 03=Boleta)
    tipo_code = '01' if venta['tipo_comprobante'] == 'Factura Electrónica' else '03'
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "InvoiceTypeCode"), listID="0101").text = tipo_code
    ET.SubElement(invoice, ET.QName(NS_MAP["cbc"], "DocumentCurrencyCode")).text = "PEN"

    # Emisor
    supplier = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "AccountingSupplierParty"))
    party_s = ET.SubElement(supplier, ET.QName(NS_MAP["cac"], "Party"))
    party_id_s = ET.SubElement(party_s, ET.QName(NS_MAP["cac"], "PartyIdentification"))
    ET.SubElement(party_id_s, ET.QName(NS_MAP["cbc"], "ID"), schemeID="6").text = config_empresa['ruc_empresa']
    party_legal_s = ET.SubElement(party_s, ET.QName(NS_MAP["cac"], "PartyLegalEntity"))
    ET.SubElement(party_legal_s, ET.QName(NS_MAP["cbc"], "RegistrationName")).text = config_empresa['razon_social']

    # Receptor
    doc_type_map = {'DNI': '1', 'RUC': '6', 'Otro': '0'}
    cliente_doc_code = doc_type_map.get(cliente.get('tipo_documento'), '0')
    cliente_num = cliente.get('numero_documento', '00000000')
    cliente_nom = f"{cliente.get('razon_social_nombres', '')} {cliente.get('apellidos', '')}".strip()

    customer = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "AccountingCustomerParty"))
    party_c = ET.SubElement(customer, ET.QName(NS_MAP["cac"], "Party"))
    party_id_c = ET.SubElement(party_c, ET.QName(NS_MAP["cac"], "PartyIdentification"))
    ET.SubElement(party_id_c, ET.QName(NS_MAP["cbc"], "ID"), schemeID=cliente_doc_code).text = cliente_num
    party_legal_c = ET.SubElement(party_c, ET.QName(NS_MAP["cac"], "PartyLegalEntity"))
    ET.SubElement(party_legal_c, ET.QName(NS_MAP["cbc"], "RegistrationName")).text = cliente_nom or "CLIENTES VARIOS"

    # Totales
    monto_total = float(venta['monto_final_venta'])
    monto_impuestos = float(venta['monto_impuestos'])
    base_imponible = monto_total - monto_impuestos

    tax_total = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "TaxTotal"))
    ET.SubElement(tax_total, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{monto_impuestos:.2f}"
    
    tax_sub = ET.SubElement(tax_total, ET.QName(NS_MAP["cac"], "TaxSubtotal"))
    ET.SubElement(tax_sub, ET.QName(NS_MAP["cbc"], "TaxableAmount"), currencyID="PEN").text = f"{base_imponible:.2f}"
    ET.SubElement(tax_sub, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{monto_impuestos:.2f}"
    
    tax_cat = ET.SubElement(tax_sub, ET.QName(NS_MAP["cac"], "TaxCategory"))
    tax_sch = ET.SubElement(tax_cat, ET.QName(NS_MAP["cac"], "TaxScheme"))
    ET.SubElement(tax_sch, ET.QName(NS_MAP["cbc"], "ID")).text = "1000"
    ET.SubElement(tax_sch, ET.QName(NS_MAP["cbc"], "Name")).text = "IGV"
    ET.SubElement(tax_sch, ET.QName(NS_MAP["cbc"], "TaxTypeCode")).text = "VAT"

    legal = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "LegalMonetaryTotal"))
    ET.SubElement(legal, ET.QName(NS_MAP["cbc"], "LineExtensionAmount"), currencyID="PEN").text = f"{base_imponible:.2f}"
    ET.SubElement(legal, ET.QName(NS_MAP["cbc"], "PayableAmount"), currencyID="PEN").text = f"{monto_total:.2f}"

    # Detalle Ítems
    for i, item in enumerate(items, 1):
        line = ET.SubElement(invoice, ET.QName(NS_MAP["cac"], "InvoiceLine"))
        ET.SubElement(line, ET.QName(NS_MAP["cbc"], "ID")).text = str(i)
        ET.SubElement(line, ET.QName(NS_MAP["cbc"], "InvoicedQuantity"), unitCode="NIU").text = str(int(item['cantidad']))
        
        p_unit = float(item['precio_unitario_venta'])
        valor_unit = p_unit / 1.18
        subtotal_neto = float(item['subtotal_item_neto'])
        valor_venta_item = subtotal_neto / 1.18
        igv_item = subtotal_neto - valor_venta_item

        ET.SubElement(line, ET.QName(NS_MAP["cbc"], "LineExtensionAmount"), currencyID="PEN").text = f"{valor_venta_item:.2f}"

        pricing = ET.SubElement(line, ET.QName(NS_MAP["cac"], "PricingReference"))
        alt = ET.SubElement(pricing, ET.QName(NS_MAP["cac"], "AlternativeConditionPrice"))
        ET.SubElement(alt, ET.QName(NS_MAP["cbc"], "PriceAmount"), currencyID="PEN").text = f"{p_unit:.2f}"
        ET.SubElement(alt, ET.QName(NS_MAP["cbc"], "PriceTypeCode")).text = "01"

        tax_line = ET.SubElement(line, ET.QName(NS_MAP["cac"], "TaxTotal"))
        ET.SubElement(tax_line, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{igv_item:.2f}"
        
        tax_sub_line = ET.SubElement(tax_line, ET.QName(NS_MAP["cac"], "TaxSubtotal"))
        ET.SubElement(tax_sub_line, ET.QName(NS_MAP["cbc"], "TaxableAmount"), currencyID="PEN").text = f"{valor_venta_item:.2f}"
        ET.SubElement(tax_sub_line, ET.QName(NS_MAP["cbc"], "TaxAmount"), currencyID="PEN").text = f"{igv_item:.2f}"
        
        tax_cat_line = ET.SubElement(tax_sub_line, ET.QName(NS_MAP["cac"], "TaxCategory"))
        ET.SubElement(tax_cat_line, ET.QName(NS_MAP["cbc"], "Percent")).text = "18.00"
        ET.SubElement(tax_cat_line, ET.QName(NS_MAP["cbc"], "TaxExemptionReasonCode")).text = "10" # Gravado - Operación Onerosa
        
        tax_sch_line = ET.SubElement(tax_cat_line, ET.QName(NS_MAP["cac"], "TaxScheme"))
        ET.SubElement(tax_sch_line, ET.QName(NS_MAP["cbc"], "ID")).text = "1000"
        ET.SubElement(tax_sch_line, ET.QName(NS_MAP["cbc"], "Name")).text = "IGV"
        ET.SubElement(tax_sch_line, ET.QName(NS_MAP["cbc"], "TaxTypeCode")).text = "VAT"

        item_node = ET.SubElement(line, ET.QName(NS_MAP["cac"], "Item"))
        ET.SubElement(item_node, ET.QName(NS_MAP["cbc"], "Description")).text = item['descripcion_item_venta']
        
        price = ET.SubElement(line, ET.QName(NS_MAP["cac"], "Price"))
        ET.SubElement(price, ET.QName(NS_MAP["cbc"], "PriceAmount"), currencyID="PEN").text = f"{valor_unit:.2f}"

    # --- 4. FIRMA DIGITAL (CORRECCIÓN CRÍTICA AQUÍ) ---
    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315" # <--- ESTO ES LO QUE PIDE SUNAT
    )
    
    cert_chain = [public_cert] + additional_certs
    signed_invoice = signer.sign(invoice, key=private_key, cert=cert_chain)
    
    # Mover la firma al lugar correcto (UBLExtension)
    signature_node = signed_invoice.find(".//ds:Signature", namespaces=NS_MAP)
    # Buscamos el ExtensionContent dentro del signed_invoice, no del invoice original
    signature_placeholder = signed_invoice.find(".//ext:ExtensionContent", namespaces=NS_MAP)
    
    if signature_placeholder is not None and signature_node is not None:
        signature_placeholder.append(signature_node)
    
    # --- 5. Serialización (SIN Pretty Print) ---
    # pretty_print=False es obligatorio para que el hash no cambie
    xml_string = ET.tostring(signed_invoice, pretty_print=False, xml_declaration=True, encoding='UTF-8')
    
    nombre_archivo = f"{config_empresa['ruc_empresa']}-{tipo_code}-{serie}-{numero}"
    
    return xml_string, nombre_archivo


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

def _procesar_envio_sunat(venta_id):
    # ... (Configuración inicial igual) ...
    SUNAT_WSDL_URL = 'https://e-factura.sunat.gob.pe/ol-ti-itcpfegem/billService?wsdl'
    
    xml_firmado_str, nombre_base = _generar_y_firmar_xml(venta_id)
    nombre_archivo_zip = f"{nombre_base}.zip"

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(f"{nombre_base}.xml", xml_firmado_str)
    zip_data = zip_buffer.getvalue()
    zip_base64 = base64.b64encode(zip_data).decode('utf-8')
    
    # Cargar Credenciales
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT ruc_empresa, usuario_sol, clave_sol FROM configuracion_sistema WHERE id = 1")
        config_sol = cursor.fetchone()

    ruc_emisor = str(config_sol.get('ruc_empresa', '')).strip()
    usuario_sol = str(config_sol.get('usuario_sol', '')).strip()
    clave_sol = str(config_sol.get('clave_sol', '')).strip()

    if usuario_sol.startswith(ruc_emisor):
        usuario_wsse = usuario_sol
    else:
        usuario_wsse = f"{ruc_emisor}{usuario_sol}"
    
    # Envío
    transport = Transport(timeout=30)
    client = Client(wsdl=SUNAT_WSDL_URL, transport=transport, wsse=UsernameToken(usuario_wsse, clave_sol))
    
    # Zeep puede devolver bytes directos o un objeto, dependiendo de la versión
    response = client.service.sendBill(fileName=nombre_archivo_zip, contentFile=zip_base64)
    
    # --- LÓGICA DE PROCESAMIENTO CDR (CORREGIDA) ---
    cdr_zip_data = None

    # Caso 1: Respuesta es bytes directos (Tu caso actual)
    if isinstance(response, bytes):
        cdr_zip_data = response
    
    # Caso 2: Respuesta es objeto con applicationResponse (Estándar)
    elif hasattr(response, 'applicationResponse'):
        cdr_zip_data = base64.b64decode(response.applicationResponse)
        
    # Caso 3: Respuesta es dict
    elif isinstance(response, dict) and 'applicationResponse' in response:
        cdr_zip_data = base64.b64decode(response['applicationResponse'])

    if cdr_zip_data:
        # Guardar CDR
        instance_path = current_app.instance_path
        cdr_path = os.path.join(instance_path, 'cdr')
        os.makedirs(cdr_path, exist_ok=True)
        nombre_cdr_zip = f"R-{nombre_base}.zip"
        
        with open(os.path.join(cdr_path, nombre_cdr_zip), 'wb') as f:
            f.write(cdr_zip_data)
        
        # Analizar XML del CDR
        try:
            with zipfile.ZipFile(io.BytesIO(cdr_zip_data), 'r') as zip_ref:
                nombre_cdr_xml = zip_ref.namelist()[0]
                with zip_ref.open(nombre_cdr_xml) as cdr_xml_file:
                    cdr_tree = ET.parse(cdr_xml_file)
                    
                    ns = {'cbc': "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"}
                    code_node = cdr_tree.find('.//cbc:ResponseCode', ns)
                    desc_node = cdr_tree.find('.//cbc:Description', ns)
                    
                    response_code = code_node.text if code_node is not None else "?"
                    response_desc = desc_node.text if desc_node is not None else "Procesado sin mensaje"
        except Exception as e:
            # Si falla leer el XML pero tenemos el ZIP, asumimos éxito parcial
            response_code = "0"
            response_desc = "CDR recibido pero no legible."

        estado_sunat = "Aceptada" if response_code == "0" else f"Rechazada ({response_code})"
        
        # Actualizar BD
        with db.cursor() as cursor:
            cursor.execute("UPDATE ventas SET estado_sunat=%s, cdr_sunat_path=%s WHERE id=%s", 
                           (estado_sunat, nombre_cdr_zip, venta_id))
            db.commit()

        if response_code != "0":
            raise Exception(f"SUNAT rechazó: {response_desc}")
        
        return f"¡ACEPTADO! {response_desc}"
    else:
        raise ValueError(f"Respuesta inesperada de SUNAT: {type(response)}")


@main_bp.route('/ventas/enviar-sunat/<int:venta_id>', methods=['POST'])
@login_required
def enviar_sunat(venta_id):
    """
    Llama a la función auxiliar para enviar el comprobante a SUNAT y maneja la respuesta.
    """
    try:
        success_message = _procesar_envio_sunat(venta_id)
        flash(success_message, 'success')
    except Fault as fault:
        flash(f"Error de SOAP al comunicarse con SUNAT: {fault.message}", "danger")
        current_app.logger.error(f"Error SOAP en enviar_sunat para venta {venta_id}: {fault}")
    except Exception as e:
        flash(f"Error al enviar a SUNAT: {e}", "danger")
        current_app.logger.error(f"Error en enviar_sunat para venta {venta_id}: {e}")

    return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))
    

# -------------------------------------------------------------------------
# API CONSULTA DNI/RUC    sk_12199.6AOBIMls8TquShJ45J3rnmPfCR0BtWcK
# -------------------------------------------------------------------------
@main_bp.route('/api/consultar-documento/<tipo>/<numero>', methods=['GET'])
@login_required
def consultar_documento_api(tipo, numero):
    # --- TU TOKEN ---
    API_TOKEN = 'sk_12199.6AOBIMls8TquShJ45J3rnmPfCR0BtWcK' 
    BASE_URL = 'https://api.decolecta.com'
    
    headers = {'Authorization': f'Bearer {API_TOKEN}', 'Content-Type': 'application/json'}

    try:
        # --- CASO DNI (RENIEC) ---
        if tipo == 'DNI':
            url = f"{BASE_URL}/v1/reniec/dni?numero={numero}"
            response = requests.get(url, headers=headers, timeout=10)
            
            # DEBUG: Para ver en terminal si algo cambia
            print(f"--- DNI {numero} ---")
            print(response.json())

            if response.status_code == 200:
                data = response.json()
                persona = data.get('data', data) or {} 

                # CORRECCIÓN DE LLAVES SEGÚN TUS LOGS:
                # La API devuelve: first_name, first_last_name, second_last_name
                nombres = persona.get('first_name') or persona.get('nombres') or ''
                ape_pat = persona.get('first_last_name') or persona.get('apellido_paterno') or ''
                ape_mat = persona.get('second_last_name') or persona.get('apellido_materno') or ''
                
                # Validamos que haya encontrado algo
                if not nombres and not ape_pat:
                    return jsonify({'success': False, 'message': 'DNI no encontrado o formato inesperado.'})

                return jsonify({
                    'success': True,
                    'tipo': 'DNI',
                    'nombres': nombres,
                    'apellido_paterno': ape_pat,
                    'apellido_materno': ape_mat,
                    'razon_social': f"{nombres} {ape_pat} {ape_mat}".strip(), # Fallback
                    'direccion': persona.get('direccion', ''),
                    'fecha_nacimiento': persona.get('birth_date', '') # A veces viene como birth_date
                })

        # --- CASO RUC (SUNAT) ---
        elif tipo == 'RUC':
            url = f"{BASE_URL}/v1/sunat/ruc?numero={numero}"
            response = requests.get(url, headers=headers, timeout=10)
            
            print(f"--- RUC {numero} ---")
            print(response.json())

            if response.status_code == 200:
                data = response.json()
                empresa = data.get('data', data) or {}

                razon_social = empresa.get('razon_social') or ''
                
                if not razon_social:
                     return jsonify({'success': False, 'message': 'RUC no encontrado.'})

                # Dirección
                dir_fiscal = empresa.get('direccion') or ''
                # A veces la dirección viene desglosada, a veces junta. Usamos lo que haya.
                
                return jsonify({
                    'success': True,
                    'tipo': 'RUC',
                    'razon_social': razon_social,
                    'direccion': dir_fiscal,
                    'condicion': empresa.get('condicion', ''),
                    'estado': empresa.get('estado', '')
                })

        return jsonify({'success': False, 'message': 'Documento no encontrado'})

    except Exception as e:
        print(f"ERROR API: {e}")
        return jsonify({'success': False, 'message': f"Error interno: {str(e)}"})
  
  
  # -------------------------------------------------------------------------
# VISTA: PANTALLA DE CANJE DE COMPROBANTE
# -------------------------------------------------------------------------
@main_bp.route('/ventas/convertir/<int:venta_id>', methods=['GET'])
@login_required
def vista_convertir_venta(venta_id):
    db_conn = get_db()
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM ventas WHERE id = %s", (venta_id,))
        venta = cursor.fetchone()
        
    if not venta or venta['tipo_comprobante'] != 'Nota de Venta':
        flash("Esta venta no se puede canjear (Ya es un comprobante fiscal o no existe).", "warning")
        return redirect(url_for('main.listar_ventas'))
        
    return render_template('ventas/convertir_venta.html', venta=venta)

# -------------------------------------------------------------------------
# PROCESO: EJECUTAR CANJE (POST)
# -------------------------------------------------------------------------
@main_bp.route('/ventas/procesar-conversion/<int:venta_id>', methods=['POST'])
@login_required
def procesar_conversion_venta(venta_id):
    db_conn = get_db()
    
    nuevo_tipo = request.form.get('nuevo_tipo')
    tipo_doc = request.form.get('tipo_doc_cliente')
    num_doc = request.form.get('num_doc_cliente')
    nombre_cliente = request.form.get('nombre_cliente')
    direccion_cliente = request.form.get('direccion_cliente')
    sucursal_id = session.get('sucursal_id')

    # Validación Estricta para Factura
    if nuevo_tipo == 'Factura Electrónica':
        if tipo_doc != 'RUC' or len(num_doc) != 11:
            flash("Error: Para Factura se requiere un RUC válido de 11 dígitos.", "danger")
            return redirect(url_for('main.vista_convertir_venta', venta_id=venta_id))
    
    try:
        with db_conn.cursor() as cursor:
            # 1. Crear o Actualizar Cliente en BD (Para que quede registrado)
            cursor.execute("SELECT id FROM clientes WHERE numero_documento = %s", (num_doc,))
            res_cli = cursor.fetchone()
            
            if res_cli:
                cliente_id = res_cli[0]
                # Opcional: Actualizar dirección si vino nueva
                cursor.execute("UPDATE clientes SET razon_social_nombres=%s, direccion=%s WHERE id=%s", 
                             (nombre_cliente, direccion_cliente, cliente_id))
            else:
                cursor.execute("""
                    INSERT INTO clientes (tipo_documento, numero_documento, razon_social_nombres, direccion)
                    VALUES (%s, %s, %s, %s) RETURNING id
                """, (tipo_doc, num_doc, nombre_cliente, direccion_cliente))
                cliente_id = cursor.fetchone()[0]

            # 2. Obtener Nueva Serie y Correlativo
            cursor.execute("""
                SELECT serie, ultimo_numero FROM series_comprobantes 
                WHERE sucursal_id = %s AND tipo_comprobante = %s FOR UPDATE
            """, (sucursal_id, nuevo_tipo))
            serie_config = cursor.fetchone()
            
            if not serie_config:
                raise Exception(f"No hay serie configurada para {nuevo_tipo} en esta sucursal.")
                
            serie = serie_config[0]
            nuevo_numero = serie_config[1] + 1
            numero_str = str(nuevo_numero).zfill(8)

            # 3. Actualizar Venta (El Canje Real)
            cursor.execute("""
                UPDATE ventas 
                SET tipo_comprobante = %s,
                    serie_comprobante = %s,
                    numero_comprobante = %s,
                    cliente_receptor_id = %s, -- Asignamos el cliente validado
                    cliente_facturacion_id = %s, -- También como facturación
                    estado_sunat = 'Pendiente' -- Listo para enviar
                WHERE id = %s
            """, (nuevo_tipo, serie, numero_str, cliente_id, cliente_id, venta_id))

            # 4. Actualizar Correlativo
            cursor.execute("""
                UPDATE series_comprobantes SET ultimo_numero = %s 
                WHERE sucursal_id = %s AND tipo_comprobante = %s
            """, (nuevo_numero, sucursal_id, nuevo_tipo))
            
            db_conn.commit()
            
            flash(f"¡Canje Exitoso! Se generó la {nuevo_tipo} {serie}-{numero_str}", "success")
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))

    except Exception as e:
        db_conn.rollback()
        flash(f"Error al procesar el canje: {e}", "danger")
        return redirect(url_for('main.vista_convertir_venta', venta_id=venta_id))  
    
@main_bp.route('/configuracion/estilos')
@login_required
@admin_required
def listar_estilos():
    """
    Muestra la lista de todos los estilos (cortes, peinados, etc.).
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM estilos ORDER BY nombre")
            estilos = cursor.fetchall()
    except Exception as err:
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
        except Exception as err:
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
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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

        except (ValueError, Exception, Exception) as e:
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
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
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
            
    except Exception as err:
        flash(f"Error al cargar el historial del cliente: {err}", "danger")
        return redirect(url_for('main.listar_clientes'))

    return render_template('clientes/detalle_cliente.html',
                           cliente=cliente,
                           historial_ventas=historial_ventas,
                           historial_membresias=historial_membresias,
                           titulo_pagina=f"Detalle de Cliente")


@main_bp.route('/configuracion/sistema', methods=['GET', 'POST'])
@login_required
@admin_required
def configurar_sistema():
    """
    Maneja la configuración general del sistema, como nombre y tema de colores.
    """
    db_conn = get_db()
    cursor = None
    
    try:
        if request.method == 'POST':
            # Recoger datos del formulario
            nombre_empresa = request.form.get('nombre_empresa')
            color_primario = request.form.get('color_primario')
            color_secundario = request.form.get('color_secundario')
            color_fondo = request.form.get('color_fondo')
            color_texto = request.form.get('color_texto')
            color_sidebar_fondo = request.form.get('color_sidebar_fondo')
            color_sidebar_texto = request.form.get('color_sidebar_texto')
            color_navbar_fondo = request.form.get('color_navbar_fondo')

            # Realizar el UPDATE
            cursor = db_conn.cursor()
            sql_update = """
                UPDATE configuracion_sistema SET
                    nombre_empresa = %s,
                    color_primario = %s,
                    color_secundario = %s,
                    color_fondo = %s,
                    color_texto = %s,
                    color_sidebar_fondo = %s,
                    color_sidebar_texto = %s,
                    color_navbar_fondo = %s
                WHERE id = 1
            """
            cursor.execute(sql_update, (nombre_empresa, color_primario, color_secundario, color_fondo, color_texto, color_sidebar_fondo, color_sidebar_texto, color_navbar_fondo))
            db_conn.commit()
            flash('Configuración del sistema actualizada exitosamente.', 'success')
            return redirect(url_for('main.configurar_sistema'))

        # Lógica GET: Obtener la configuración actual
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM configuracion_sistema WHERE id = 1")
        config_data = cursor.fetchone()

        # Si no hay configuración, podrías insertar una por defecto o manejarlo en la plantilla
        if not config_data:
            flash("No se encontró la configuración del sistema. Puede que necesite ser inicializada.", "warning")
            # Podrías pasar un diccionario vacío o con valores por defecto
            config_data = {}

        return render_template('configuracion/sistema.html', config=config_data, titulo_pagina="Configuración del Sistema")

    except Exception as e:
        if db_conn:
            db_conn.rollback()
        flash(f"Ocurrió un error al procesar la configuración: {e}", "danger")
        current_app.logger.error(f"Error en configurar_sistema: {e}")
        # En caso de error, es mejor redirigir o mostrar una plantilla de error
        # que re-renderizar con datos potencialmente inconsistentes.
    finally:
        if cursor:
            cursor.close()

    
# -------------------------------------------------------------------------
# RUTAS PARA IMPRESIÓN Y EMISIÓN DE COMPROBANTES (Faltaban estas)
# -------------------------------------------------------------------------

@main_bp.route('/ventas/<int:venta_id>/emitir_comprobante', methods=['GET', 'POST'])
@login_required
def emitir_comprobante(venta_id):
    """
    Muestra la pantalla para seleccionar si se emite Boleta o Factura (GET)
    y procesa la emisión del comprobante (POST) usando el esquema de BD actualizado.
    """
    db_conn = get_db()
    cursor = None

    try:
        if request.method == 'POST':
            db_conn.autocommit = False
            cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            tipo_comprobante_form = request.form.get('tipo_comprobante')
            cliente_facturacion_id = request.form.get('cliente_facturacion_id', type=int)

            if not tipo_comprobante_form or not cliente_facturacion_id:
                raise ValueError("Debe seleccionar un tipo de comprobante y un cliente.")

            if tipo_comprobante_form == 'Factura':
                cursor.execute("SELECT tipo_documento FROM clientes WHERE id = %s", (cliente_facturacion_id,))
                cliente = cursor.fetchone()
                if not cliente or cliente['tipo_documento'] != 'RUC':
                    raise ValueError("Para emitir una Factura, el cliente debe tener un RUC registrado.")

            cursor.execute("SELECT sucursal_id FROM ventas WHERE id = %s", (venta_id,))
            venta = cursor.fetchone()
            if not venta:
                raise ValueError("La venta original no fue encontrada.")
            
            tipo_map = {'Boleta': 'Boleta Electrónica', 'Factura': 'Factura Electrónica'}
            tipo_comprobante_db = tipo_map.get(tipo_comprobante_form)

            cursor.execute(
                "SELECT id, serie, ultimo_numero FROM series_comprobantes WHERE sucursal_id = %s AND tipo_comprobante = %s FOR UPDATE",
                (venta['sucursal_id'], tipo_comprobante_db)
            )
            serie_info = cursor.fetchone()
            if not serie_info:
                raise ValueError(f"No hay una serie configurada para '{tipo_comprobante_db}' en esta sucursal.")

            nuevo_numero = serie_info['ultimo_numero'] + 1
            numero_formateado = f"{nuevo_numero:08d}"
            serie_comprobante = serie_info['serie']

            cursor.execute("""
                UPDATE ventas 
                SET tipo_comprobante = %s, serie_comprobante = %s, numero_comprobante = %s, cliente_facturacion_id = %s
                WHERE id = %s
            """, (tipo_comprobante_db, serie_comprobante, numero_formateado, cliente_facturacion_id, venta_id))

            cursor.execute(
                "UPDATE series_comprobantes SET ultimo_numero = %s WHERE id = %s",
                (nuevo_numero, serie_info['id'])
            )

            db_conn.commit()

            # Intento de envío inmediato a SUNAT
            try:
                success_message = _procesar_envio_sunat(venta_id)
                flash(f'Comprobante {serie_comprobante}-{numero_formateado} generado.', 'success')
                flash(success_message, 'success')
            except Exception as e:
                current_app.logger.error(f"Envío automático a SUNAT falló para venta {venta_id}: {e}")
                flash(f'Comprobante {serie_comprobante}-{numero_formateado} generado, pero el envío a SUNAT falló. Intente desde el historial.', 'warning')
            
            return redirect(url_for('main.listar_ventas'))

        # Lógica GET
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT v.*, c.razon_social_nombres, c.apellidos, c.apoderado_id FROM ventas v JOIN clientes c ON v.cliente_receptor_id = c.id WHERE v.id = %s", (venta_id,))
        venta = cursor.fetchone()
        if not venta:
            flash('Venta no encontrada.', 'danger')
            return redirect(url_for('main.listar_ventas'))

        cliente_sugerido = None
        if venta['apoderado_id']:
            cursor.execute("SELECT * FROM clientes WHERE id = %s", (venta['apoderado_id'],))
            cliente_sugerido = cursor.fetchone()
        else:
            cliente_sugerido = venta
            
        return render_template('ventas/emitir_comprobante.html', venta=venta, cliente_sugerido=cliente_sugerido)

    except (Exception, psycopg2.Error) as e:
        if db_conn:
            db_conn.rollback()
        flash(f"Error al emitir comprobante: {e}", 'danger')
        current_app.logger.error(f"Error en emitir_comprobante para venta {venta_id}: {e}")
        return redirect(url_for('main.emitir_comprobante', venta_id=venta_id))
    
    finally:
        if db_conn:
            db_conn.autocommit = True
        if cursor:
            cursor.close()


@main_bp.route('/ventas/ticket/<int:venta_id>')
@login_required
def imprimir_ticket(venta_id):
    """
    Genera una vista simple HTML para imprimir en ticketera térmica.
    """
    try:
        db = get_db()
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Cabecera
            cursor.execute("""
                SELECT 
                    v.*,
                    TO_CHAR(v.fecha_venta, 'DD/MM/YYYY HH24:MI') as fecha_formateada,
                    s.nombre AS sucursal_nombre, 
                    s.direccion AS sucursal_direccion, 
                    s.telefono AS sucursal_telefono,
                    e.nombre_display AS colaborador_nombre,
                    cl.razon_social_nombres, 
                    cl.apellidos,
                    cl.numero_documento,
                    cl.tipo_documento
                FROM ventas v
                JOIN sucursales s ON v.sucursal_id = s.id
                JOIN empleados e ON v.empleado_id = e.id
                LEFT JOIN clientes cl ON v.cliente_receptor_id = cl.id
                WHERE v.id = %s
            """, (venta_id,))
            venta = cursor.fetchone()
            
            # Detalle
            cursor.execute("""
                SELECT descripcion_item_venta, cantidad, precio_unitario_venta, subtotal_item_neto
                FROM venta_items
                WHERE venta_id = %s
            """, (venta_id,))
            items = cursor.fetchall()
            
            # Pagos
            cursor.execute("SELECT * FROM venta_pagos WHERE venta_id = %s", (venta_id,))
            pagos = cursor.fetchall()
            
            return render_template('ventas/ticket_venta.html', venta=venta, items=items, pagos=pagos)
            
    except Exception as e:
        return f"Error generando ticket: {e}"
    
    
@main_bp.route('/ventas/cdr/<int:venta_id>')
@login_required
def descargar_cdr(venta_id):
    """
    Permite descargar el archivo CDR (respuesta de SUNAT) si existe.
    """
    db_conn = get_db()  
    
    try:
        # 1. Buscar nombre del CDR en la BD
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT cdr_sunat_path FROM ventas WHERE id = %s", (venta_id,))
            venta = cursor.fetchone()
            
        if not venta or not venta.get('cdr_sunat_path'):
            flash("Esta venta no tiene un CDR asociado.", "warning")
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))
            
        # 2. Construir ruta al archivo
        instance_path = current_app.instance_path
        cdr_filename = venta['cdr_sunat_path']
        cdr_full_path = os.path.join(instance_path, 'cdr', cdr_filename)
        
        # 3. Enviar archivo
        if os.path.exists(cdr_full_path):
            return send_file(cdr_full_path, as_attachment=True, download_name=cdr_filename)
        else:
            flash(f"El archivo CDR ({cdr_filename}) no se encuentra en el servidor.", "danger")
            return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id))
            
    except Exception as e:
        flash(f"Error al descargar CDR: {e}", "danger")
        return redirect(url_for('main.ver_detalle_venta', venta_id=venta_id)) 
 
  
  # Agrega esto en routes.py

@main_bp.route('/api/reservas/<int:reserva_id>/whatsapp-link', methods=['GET'])
@login_required
def obtener_link_whatsapp_reserva(reserva_id):
    """Genera link de WhatsApp para una reserva existente (Recordatorio o Info)."""
    tipo_mensaje = request.args.get('tipo', 'recordatorio') # Por defecto recordatorio
    
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # 1. Obtener datos completos de la reserva
        sql = """
            SELECT 
                r.id, r.fecha_hora_inicio, 
                c.razon_social_nombres as cliente, c.telefono,
                s.nombre as servicio,
                e.nombres as staff
            FROM reservas r
            JOIN clientes c ON r.cliente_id = c.id
            JOIN servicios s ON r.servicio_id = s.id
            JOIN empleados e ON r.empleado_id = e.id
            WHERE r.id = %s
        """
        cursor.execute(sql, (reserva_id,))
        reserva = cursor.fetchone()
        
        if not reserva:
            return jsonify({'success': False, 'message': 'Reserva no encontrada'}), 404
            
        if not reserva['telefono']:
            return jsonify({'success': False, 'message': 'El cliente no tiene teléfono registrado'}), 400

        # 2. Obtener plantilla
        cursor.execute("SELECT contenido FROM plantillas_whatsapp WHERE tipo = %s", (tipo_mensaje,))
        tpl = cursor.fetchone()
        
        if not tpl:
            return jsonify({'success': False, 'message': 'Plantilla no encontrada'}), 404

        # 3. Construir mensaje
        try:
            plantilla_raw = tpl['contenido']
            plantilla_limpia = plantilla_raw.replace('%0A', '\n').replace('\\n', '\n')
            
            # Formatos de fecha
            fecha_dt = reserva['fecha_hora_inicio']
            msg = plantilla_limpia.format(
                cliente=reserva['cliente'],
                fecha=fecha_dt.strftime('%d/%m/%Y'),
                hora=fecha_dt.strftime('%I:%M %p'),
                servicio=reserva['servicio'],
                staff=reserva['staff']
            )
            
            # Formato teléfono
            tel = str(reserva['telefono']).strip().replace(' ', '').replace('.0', '')
            if len(tel) == 9: tel = f"51{tel}"
            
            # Generar URL App
            url = f"whatsapp://send?phone={tel}&text={quote(msg)}"
            
            return jsonify({'success': True, 'url': url})
            
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
        

# 🟢 Asegúrate de tener 'quote' importado arriba: from urllib.parse import quote

# 🟢 Función Helper para Google Calendar (Ponla fuera de las rutas, arriba)
def generar_link_google_calendar(titulo, inicio, fin, detalle, ubicacion="JV Studio"):
    base = "https://www.google.com/calendar/render?action=TEMPLATE"
    fmt = "%Y%m%dT%H%M%S"
    fechas = f"{inicio.strftime(fmt)}/{fin.strftime(fmt)}"
    return f"{base}&text={quote(titulo)}&dates={fechas}&details={quote(detalle)}&location={quote(ubicacion)}&sf=true&output=xml"

# 🟢 La Ruta para los Botones del Modal
@main_bp.route('/api/reservas/<int:reserva_id>/whatsapp-link', methods=['GET'])
@login_required
def generar_link_reserva_existente(reserva_id):
    tipo = request.args.get('tipo', 'recordatorio') 
    db = get_db()
    
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Obtener datos
            cursor.execute("""
                SELECT 
                    r.id, r.fecha_hora_inicio, r.fecha_hora_fin, r.notas_cliente,
                    c.razon_social_nombres as cliente, c.telefono as tel_cliente,
                    s.nombre as servicio, 
                    e.nombres as staff, e.telefono as tel_staff
                FROM reservas r
                LEFT JOIN clientes c ON r.cliente_id = c.id
                LEFT JOIN servicios s ON r.servicio_id = s.id
                LEFT JOIN empleados e ON r.empleado_id = e.id
                WHERE r.id = %s
            """, (reserva_id,))
            res = cursor.fetchone()
            
            if not res: 
                print("❌ [DEBUG] Reserva no encontrada en BD")
                return jsonify({'success': False, 'message': 'Reserva no encontrada'}), 404

            # 🔍 2. DATOS CRUDOS
            print(f"   [DEBUG] Datos crudos BD: Staff={res.get('staff')}, TelStaff={res.get('tel_staff')} \n")
            
            if not res: return jsonify({'success': False, 'message': 'Reserva no encontrada'}), 404

            # 2. 🟢 INICIALIZACIÓN OBLIGATORIA (Esto arregla el KeyError)
            # Definimos estas variables vacías AQUÍ para que existan pase lo que pase
            link_cal_final = "" 
            telefono_destino = ""
            plantilla_nombre = "recordatorio"

            # Datos seguros
            staff_txt = res['staff'] or "Sin asignar"
            cliente_txt = res['cliente'] or "Cliente"
            servicio_txt = res['servicio'] or "Servicio"

            # 3. Lógica
            if tipo == 'aviso_staff':
                plantilla_nombre = 'aviso_staff'
                # Verificamos si hay staff REAL
                if not res['staff'] or not res['tel_staff']:
                    return jsonify({'success': False, 'message': '❌ Error: Esta reserva no tiene un Colaborador asignado (o no tiene teléfono). Edita la reserva y asigna uno primero.'}), 400
                
                telefono_destino = res['tel_staff']
                
                # Generar Calendario
                try:
                    link_cal_final = generar_link_google_calendar(
                        titulo=f"Cita: {cliente_txt}",
                        inicio=res['fecha_hora_inicio'],
                        fin=res['fecha_hora_fin'],
                        detalle=f"Servicio: {servicio_txt}"
                    )
                except:
                    link_cal_final = ""
            else:
                # Recordatorio Cliente
                if not res['tel_cliente']:
                    return jsonify({'success': False, 'message': 'El cliente no tiene teléfono.'}), 400
                telefono_destino = res['tel_cliente']
                plantilla_nombre = 'recordatorio'

            # 4. Plantilla
            cursor.execute("SELECT contenido FROM plantillas_whatsapp WHERE tipo = %s", (plantilla_nombre,))
            tpl = cursor.fetchone()
            texto = tpl['contenido'] if tpl else "Hola {cliente}, cita {fecha}."
            texto = texto.replace('%0A', '\n').replace('\\n', '\n')

            # 5. Rellenar (Con link_calendar seguro)
            datos = {
                'cliente': cliente_txt,
                'staff': staff_txt,
                'servicio': servicio_txt,
                'fecha': res['fecha_hora_inicio'].strftime('%d/%m/%Y'),
                'hora': res['fecha_hora_inicio'].strftime('%I:%M %p'),
                'link_calendar': link_cal_final # <--- Ahora esto SIEMPRE existe
            }

            try:
                msg = texto.format(**datos)
            except KeyError as e:
                # Si falla, devolvemos un mensaje genérico seguro
                msg = f"Hola {cliente_txt}, tienes una cita el {datos['fecha']} a las {datos['hora']}."

            # 6. Link
            tel = str(telefono_destino).strip().replace('.0', '').replace(' ', '')
            if len(tel) == 9: tel = "51" + tel
            
            return jsonify({'success': True, 'url': f"whatsapp://send?phone={tel}&text={quote(msg)}"})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500    
    