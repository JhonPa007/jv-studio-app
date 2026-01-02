from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
from .db import get_db

marketing_bp = Blueprint('marketing', __name__, url_prefix='/marketing')

# ==============================================================================
# ==============================================================================
# 1. FIDELIZACIÓN (LOYALTY) - CONFIGURACIÓN
# ==============================================================================

@marketing_bp.route('/setup-db')
def setup_db():
    db = get_db()
    try:
        with db.cursor() as cursor:
            # Table Loyalty
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_rules (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    servicio_id INTEGER REFERENCES servicios(id), -- Deprecated but kept for compatibility
                    cantidad_requerida INTEGER NOT NULL,
                    periodo_meses INTEGER NOT NULL,
                    descuento_porcentaje NUMERIC(5, 2) NOT NULL,
                    activo BOOLEAN DEFAULT TRUE
                );
            """)
            # Junction Table: Loyalty Rule <-> Services (M:N)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS loyalty_rule_services (
                    loyalty_rule_id INTEGER REFERENCES loyalty_rules(id) ON DELETE CASCADE,
                    servicio_id INTEGER REFERENCES servicios(id) ON DELETE CASCADE,
                    PRIMARY KEY (loyalty_rule_id, servicio_id)
                );
            """)
            # Table CRM
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crm_config (
                    id SERIAL PRIMARY KEY,
                    tipo_evento VARCHAR(50) NOT NULL,
                    mensaje_plantilla TEXT,
                    dias_anticipacion INTEGER DEFAULT 0,
                    activo BOOLEAN DEFAULT TRUE
                );
            """)
            db.commit()
            return "✅ Esquema actualizado: 'loyalty_rule_services' creada. <a href='/marketing/fidelidad'>Volver</a>"
    except Exception as e:
        db.rollback()
        return f"❌ Error creando tablas: {e}"

@marketing_bp.route('/fidelidad', methods=['GET'])
@login_required
def listar_reglas_fidelidad():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM loyalty_rules ORDER BY nombre")
        reglas = cursor.fetchall()
        
        # Hydrate services for each rule
        for r in reglas:
            cursor.execute("""
                SELECT s.nombre 
                FROM loyalty_rule_services lrs
                JOIN servicios s ON lrs.servicio_id = s.id
                WHERE lrs.loyalty_rule_id = %s
            """, (r['id'],))
            s_rows = cursor.fetchall()
            if s_rows:
                r['servicios_nombres'] = ", ".join([x['nombre'] for x in s_rows])
            else:
                # Fallback for old rules
                if r.get('servicio_id'):
                    cursor.execute("SELECT nombre FROM servicios WHERE id = %s", (r['servicio_id'],))
                    s_old = cursor.fetchone()
                    r['servicios_nombres'] = s_old['nombre'] if s_old else "Sin servicio"
                else:
                    r['servicios_nombres'] = "Todos / Ninguno"

        # Cargar servicios para el modal de nueva regla
        cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
        servicios = cursor.fetchall()
        
    return render_template('marketing/lista_reglas.html', reglas=reglas, servicios=servicios)

@marketing_bp.route('/fidelidad/guardar', methods=['POST'])
@login_required
def guardar_regla_fidelidad():
    nombre = request.form.get('nombre')
    servicios_ids = request.form.getlist('servicios_ids[]') # Recibimos lista
    cantidad = request.form.get('cantidad_requerida')
    periodo = request.form.get('periodo_meses')
    descuento = request.form.get('descuento_porcentaje')
    
    db = get_db()
    try:
        with db.cursor() as cursor:
            # 1. Insertar Regla Maestra (sin servicio_id unico)
            cursor.execute("""
                INSERT INTO loyalty_rules (nombre, cantidad_requerida, periodo_meses, descuento_porcentaje, activo)
                VALUES (%s, %s, %s, %s, TRUE) RETURNING id
            """, (nombre, cantidad, periodo, descuento))
            new_id = cursor.fetchone()[0]
            
            # 2. Insertar Relaciones M:N
            if servicios_ids:
                for sid in servicios_ids:
                    cursor.execute("INSERT INTO loyalty_rule_services (loyalty_rule_id, servicio_id) VALUES (%s, %s)", (new_id, sid))
            
            db.commit()
            flash("Regla de fidelización creada correctamente.", "success")
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
    Ahora verifica si el servicio pertenece a algun grupo de regla.
    """
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # 1. Buscar si hay una regla que incluya este servicio
        cursor.execute("""
            SELECT r.* 
            FROM loyalty_rules r
            JOIN loyalty_rule_services lrs ON r.id = lrs.loyalty_rule_id
            WHERE lrs.servicio_id = %s AND r.activo = TRUE
            LIMIT 1
        """, (servicio_id,))
        regla = cursor.fetchone()
        
        # Fallback: Revisar si hay regla legacy (columna servicio_id)
        if not regla:
            cursor.execute("SELECT * FROM loyalty_rules WHERE servicio_id = %s AND activo = TRUE LIMIT 1", (servicio_id,))
            regla = cursor.fetchone()

        if not regla:
            return jsonify({'eligible': False, 'message': 'No hay regla loyalty para este servicio'})

        # 2. Analizar historial (Multi-Servicio)
        # Contamos cuántos servicios DE LOS QUE ESTÁN EN LA REGLA se ha hecho el cliente.
        rule_id = regla['id']
        cantidad_req = regla['cantidad_requerida']
        periodo_meses = regla['periodo_meses'] 
        
        cursor.execute("SELECT CURRENT_DATE - INTERVAL '%s months'", (periodo_meses,))
        fecha_limite = cursor.fetchone()[0]
        
        # Obtenemos TODOS los servicios que cuentan para esta regla
        cursor.execute("SELECT servicio_id FROM loyalty_rule_services WHERE loyalty_rule_id = %s", (rule_id,))
        rows = cursor.fetchall()
        
        target_service_ids = [r[0] for r in rows] # Lista de IDs
        # Si esta vacio (legacy), usamos el propio del parametro
        if not target_service_ids and regla.get('servicio_id'):
            target_service_ids = [regla['servicio_id']]
            
        if not target_service_ids:
             return jsonify({'eligible': False, 'message': 'Regla sin servicios config.'})

        # Convert list to tuple for SQL IN clause
        target_service_ids_tuple = tuple(target_service_ids)
        
        query = """
            SELECT v.fecha_venta 
            FROM venta_items vi
            JOIN ventas v ON vi.venta_id = v.id
            WHERE v.cliente_id = %s 
              AND vi.servicio_id IN %s
              AND v.fecha_venta >= %s
              AND v.estado != 'Anulada'
            ORDER BY v.fecha_venta DESC
            LIMIT %s
        """
        # Fix for tuple with 1 element needing trailing comma which python generic tuple does, 
        # but execute handles tuple gracefully if param is %s? No, for IN we usually need tuple 
        # logic. Psycopg2 handles tuple adaptation automatically for IN.
        
        cursor.execute(query, (cliente_id, target_service_ids_tuple, fecha_limite, cantidad_req + 2))
        
        historial = cursor.fetchall()
        count = len(historial)
        
        if count >= cantidad_req:
            return jsonify({
                'eligible': True, 
                'discount_pct': float(regla['descuento_porcentaje']),
                'message': f"¡Felicidades! Tiene {count} visitas acumuladas (Regla: {regla['nombre']}).",
                'rule_id': regla['id']
            })
        else:
            return jsonify({
                'eligible': False, 
                'message': f"Lleva {count}/{cantidad_req} visitas en los últimos {periodo_meses} meses."
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
