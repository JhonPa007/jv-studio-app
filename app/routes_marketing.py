from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
from .db import get_db

marketing_bp = Blueprint('marketing', __name__, url_prefix='/marketing')

# ==============================================================================
# 1. FIDELIZACIÓN (LOYALTY) - CONFIGURACIÓN
# ==============================================================================

@marketing_bp.route('/fidelidad', methods=['GET'])
@login_required
def listar_reglas_fidelidad():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("""
            SELECT l.*, s.nombre as servicio_nombre 
            FROM loyalty_rules l
            JOIN servicios s ON l.servicio_id = s.id
            ORDER BY l.nombre
        """)
        reglas = cursor.fetchall()
        
        # Cargar servicios para el modal de nueva regla
        cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
        servicios = cursor.fetchall()
        
    return render_template('marketing/lista_reglas.html', reglas=reglas, servicios=servicios)

@marketing_bp.route('/fidelidad/guardar', methods=['POST'])
@login_required
def guardar_regla_fidelidad():
    nombre = request.form.get('nombre')
    servicio_id = request.form.get('servicio_id')
    cantidad = request.form.get('cantidad_requerida')
    periodo = request.form.get('periodo_meses')
    descuento = request.form.get('descuento_porcentaje')
    
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO loyalty_rules (nombre, servicio_id, cantidad_requerida, periodo_meses, descuento_porcentaje, activo)
                VALUES (%s, %s, %s, %s, %s, TRUE)
            """, (nombre, servicio_id, cantidad, periodo, descuento))
            db.commit()
            flash("Regla de fidelización creada.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")
        
    return redirect(url_for('marketing.listar_reglas_fidelidad'))

@marketing_bp.route('/fidelidad/eliminar/<int:id>', methods=['POST'])
@login_required
def eliminar_regla_fidelidad(id):
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM loyalty_rules WHERE id = %s", (id,))
            db.commit()
            flash("Regla eliminada.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for('marketing.listar_reglas_fidelidad'))


# ==============================================================================
# 2. FIDELIZACIÓN - CHECK API (Para Punto de Venta)
# ==============================================================================

@marketing_bp.route('/api/check-loyalty/<int:cliente_id>/<int:servicio_id>', methods=['GET'])
@login_required
def check_loyalty_status(cliente_id, servicio_id):
    """
    Verifica si el cliente cumple la regla para este servicio.
    Retorna: { 'eligible': Bool, 'discount_pct': Float, 'reason': Str }
    """
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # 1. Buscar regla activa para este servicio
        cursor.execute("""
            SELECT * FROM loyalty_rules 
            WHERE servicio_id = %s AND activo = TRUE
            LIMIT 1
        """, (servicio_id,))
        regla = cursor.fetchone()
        
        if not regla:
            return jsonify({'eligible': False, 'message': 'No hay regla loyalty para este servicio'})

        # 2. Analizar historial del cliente
        cantidad_req = regla['cantidad_requerida'] # Ej: 5
        periodo_meses = regla['periodo_meses']     # Ej: 3
        
        # Buscamos los ULTIMOS (cantidad_req) servicios de ese tipo que se haya hecho el cliente
        # dentro del periodo de tiempo.
        
        # Fecha límite hacia atrás
        cursor.execute("SELECT CURRENT_DATE - INTERVAL '%s months'", (periodo_meses,))
        fecha_limite = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT v.fecha_venta 
            FROM venta_items vi
            JOIN ventas v ON vi.venta_id = v.id
            WHERE v.cliente_id = %s 
              AND vi.servicio_id = %s
              AND v.fecha_venta >= %s
              AND v.estado != 'Anulada'
            ORDER BY v.fecha_venta DESC
            LIMIT %s
        """, (cliente_id, servicio_id, fecha_limite, cantidad_req + 2)) # Traemos un poco mas para verificar
        
        historial = cursor.fetchall()
        count = len(historial)
        
        # LÓGICA:
        # Si la regla dice "Despues de 5 cortes, el 6to es gratis/descuento".
        # Significa que debe tener YA 5 cortes pagados en el historial reciente.
        # Y este sería el 6to.
        
        if count >= cantidad_req:
            # ¡Cumple!
            # Verificamos si el último corte NO fue ya bonificado (para no dar doble premio?)
            # Sería complejo verificar uso. Asumiremos por cantidad pura en ventana de tiempo.
            # Una mejora sería marcar los cortes "usados" para loyalty. Por ahora, conteo simple.
            
            return jsonify({
                'eligible': True, 
                'discount_pct': float(regla['descuento_porcentaje']),
                'message': f"¡Cliente fiel! Tiene {count} servicios recientes. Aplica {regla['descuento_porcentaje']}% de dcto.",
                'rule_id': regla['id']
            })
        else:
            return jsonify({
                'eligible': False, 
                'message': f"Lleva {count}/{cantidad_req} servicios en los últimos {periodo_meses} meses."
            })

# ==============================================================================
# 3. CRM - CONFIGURACIÓN
# ==============================================================================

@marketing_bp.route('/crm', methods=['GET'])
@login_required
def listar_crm_config():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM crm_config ORDER BY id")
        configs = cursor.fetchall()
    return render_template('marketing/lista_crm.html', configs=configs)

@marketing_bp.route('/crm/guardar', methods=['POST'])
@login_required
def guardar_crm_config():
    tipo = request.form.get('tipo_evento')
    mensaje = request.form.get('mensaje_plantilla')
    dias = request.form.get('dias_anticipacion')
    
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO crm_config (tipo_evento, mensaje_plantilla, dias_anticipacion, activo)
                VALUES (%s, %s, %s, TRUE)
            """, (tipo, mensaje, dias))
            db.commit()
            flash("Configuración CRM guardada.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")
        
    return redirect(url_for('marketing.listar_crm_config'))
