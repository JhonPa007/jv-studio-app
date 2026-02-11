from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
import random
import string
import os
from .db import get_db
from .utils.gift_card_generator import generate_gift_card_image
from .utils.gift_card_pdf_generator import generate_gift_card_pdf
from flask import send_file

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

            # Columna Anti-Double-Dip
            try:
                cursor.execute("ALTER TABLE venta_items ADD COLUMN IF NOT EXISTS loyalty_consumption_group_id VARCHAR(50)")
            except Exception:
                pass 

            # Columna Puntos en Clientes
            try:
                cursor.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS puntos_acumulados INTEGER DEFAULT 0")
            except Exception:
                pass

            # Tabla Historial Puntos
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS puntos_historial (
                    id SERIAL PRIMARY KEY,
                    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
                    venta_id INTEGER REFERENCES ventas(id) ON DELETE SET NULL,
                    monto_puntos INTEGER NOT NULL,
                    tipo_transaccion VARCHAR(20) NOT NULL, -- 'ACUMULA', 'CANJE', 'AJUSTE'
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    descripcion TEXT
                );
            """)

            db.commit()
            return "✅ Esquema Actualizado: Puntos, Historial y Consumo. <a href='/marketing/fidelidad'>Volver</a>"
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
# Helper: Consumir Items (Anti-Double-Dip)
# ==============================================================================
def consumir_items_fidelidad(cliente_id, rule_id, group_id):
    """
    Marca los items más antiguos como consumidos para una regla específica.
    group_id: Identificador unico de este canje (ej. "CANJE_VENTA_123")
    """
    db = get_db()
    try:
        with db.cursor() as cursor:
            # 1. Obtener datos de la regla
            cursor.execute("SELECT * FROM loyalty_rules WHERE id = %s", (rule_id,))
            regla = cursor.fetchone()
            if not regla: return False

            cantidad = regla['cantidad_requerida']
            periodo = regla['periodo_meses']

            # 2. Obtener servicios de la regla
            cursor.execute("SELECT servicio_id FROM loyalty_rule_services WHERE loyalty_rule_id = %s", (rule_id,))
            s_rows = cursor.fetchall()
            target_ids = tuple([r[0] for r in s_rows])
            
            if not target_ids and regla.get('servicio_id'):
                target_ids = (regla['servicio_id'],)

            # 3. Buscar items elegibles (FIFO)
            cursor.execute("SELECT CURRENT_DATE - INTERVAL '%s months'", (periodo,))
            fecha_limite = cursor.fetchone()[0]

            query = """
                SELECT vi.id 
                FROM venta_items vi
                JOIN ventas v ON vi.venta_id = v.id
                WHERE v.cliente_id = %s 
                  AND vi.servicio_id IN %s
                  AND v.fecha_venta >= %s
                  AND (vi.loyalty_consumption_group_id IS NULL OR vi.loyalty_consumption_group_id = '')
                  AND v.estado != 'Anulada'
                ORDER BY v.fecha_venta ASC
                LIMIT %s
            """
            cursor.execute(query, (cliente_id, target_ids, fecha_limite, cantidad))
            items_to_update = cursor.fetchall()

            # 4. Actualizar
            ids_list = [i[0] for i in items_to_update]
            if ids_list:
                cursor.execute("""
                    UPDATE venta_items 
                    SET loyalty_consumption_group_id = %s 
                    WHERE id = ANY(%s)
                """, (str(group_id), ids_list))
                db.commit()
                return len(ids_list)
            return 0
    except Exception as e:
        db.rollback()
        print(f"Error consumiendo fidelidad: {e}")
        return 0


# ==============================================================================
# 3. MÓDULO DE CONSULTA Y PUNTOS
# ==============================================================================
@marketing_bp.route('/consultar-cliente')
@login_required
def consultar_cliente():
    return render_template('marketing/consultar_cliente.html')

@marketing_bp.route('/api/clientes/buscar', methods=['GET'])
@login_required
def api_buscar_clientes_marketing():
    """
    API para buscar clientes por nombre o DNI.
    Retorna JSON compatible con Consultar Cliente.
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Búsqueda insensible a mayúsculas
            search_pattern = f"%{q}%"
            cursor.execute("""
                SELECT id, razon_social_nombres, apellidos, numero_documento, telefono 
                FROM clientes 
                WHERE 
                    razon_social_nombres ILIKE %s OR 
                    apellidos ILIKE %s OR 
                    numero_documento ILIKE %s
                ORDER BY razon_social_nombres LIMIT 10
            """, (search_pattern, search_pattern, search_pattern))
            
            resultados = cursor.fetchall()
            
            # Formatear respuesta
            data = []
            for r in resultados:
                full_name = f"{r['razon_social_nombres']} {r['apellidos'] or ''}".strip()
                data.append({
                    'id': r['id'],
                    'nombre': full_name,
                    'documento': r['numero_documento'],
                    'telefono': r['telefono']
                })
            
            return jsonify(data)
    except Exception as e:
        print(f"Error buscando clientes API: {e}")
        return jsonify([]), 500


@marketing_bp.route('/api/client-status/<int:cliente_id>')
@login_required
def get_client_status(cliente_id):
    db = get_db()
    try:
        data = {
            'puntos': 0,
            'reglas': [],
            'reglas': [],
            'historial_puntos': [],
            'cliente_nombre': '',
            'cliente_telefono': ''
        }
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Datos Cliente & Puntos
            cursor.execute("SELECT razon_social_nombres, telefono, puntos_fidelidad FROM clientes WHERE id = %s", (cliente_id,))
            row = cursor.fetchone()
            if row:
                data['puntos'] = row['puntos_fidelidad'] or 0
                data['cliente_nombre'] = row['razon_social_nombres'] or ''
                data['cliente_telefono'] = row['telefono'] or ''

            # 2. Reglas Activas
            cursor.execute("SELECT * FROM loyalty_rules WHERE activo = TRUE")
            rules = cursor.fetchall()
            
            for r in rules:
                # Calcular progreso para cada regla
                cursor.execute("SELECT CURRENT_DATE - INTERVAL '%s months'", (r['periodo_meses'],))
                fecha_limite = cursor.fetchone()['?column?'] # Result of expression
                
                # Servicios de la regla
                cursor.execute("SELECT servicio_id FROM loyalty_rule_services WHERE loyalty_rule_id = %s", (r['id'],))
                sids = [x['servicio_id'] for x in cursor.fetchall()]
                if not sids and r['servicio_id']: sids = [r['servicio_id']]
                
                if not sids: continue
                
                cursor.execute("""
                    SELECT v.fecha_venta 
                    FROM venta_items vi 
                    JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.cliente_receptor_id = %s AND vi.servicio_id = ANY(%s) 
                    AND v.fecha_venta >= %s
                    AND v.estado != 'Anulada'
                    AND (vi.loyalty_consumption_group_id IS NULL OR vi.loyalty_consumption_group_id = '')
                    ORDER BY v.fecha_venta DESC
                """, (cliente_id, sids, fecha_limite))
                
                visitas = cursor.fetchall()
                count = len(visitas)
                
                # Calcular Limite exacto (Fecha del primer item + Periodo)
                fecha_vencimiento = None
                if visitas:
                     # El mas antiguo es el ultimo de la lista por DESC order, PERO
                     # para saber cuando vence el bloque actual, tomamos el mas antiguo valido.
                     # "Tienes hasta X fecha para completar"
                     oldest_visit = visitas[-1]['fecha_venta'] # Actually datetime
                     
                     # Sumar meses (aproximado)
                     try:
                        from dateutil.relativedelta import relativedelta
                        deadline = oldest_visit + relativedelta(months=r['periodo_meses'])
                        fecha_vencimiento = deadline.strftime('%d/%m/%Y')
                     except:
                        pass 

                data['reglas'].append({
                    'nombre': r['nombre'],
                    'progreso': count,
                    'meta': r['cantidad_requerida'],
                    'descuento': float(r['descuento_porcentaje']),
                    'vence': fecha_vencimiento if count > 0 else '-'
                })

            # 3. Historial (Ultimos 5)
            cursor.execute("""
                SELECT * FROM puntos_historial 
                WHERE cliente_id = %s 
                ORDER BY fecha_registro DESC LIMIT 5
            """, (cliente_id,))
            hist = cursor.fetchall()
            for h in hist:
                data['historial_puntos'].append({
                    'fecha': h['fecha_registro'].strftime('%d/%m %H:%M'),
                    'tipo': h['tipo_transaccion'],
                    'monto': h['monto_puntos'],
                    'desc': h['descripcion']
                })

        return jsonify(data)
    except Exception as e:
        print(e)
        return jsonify({'error': str(e)}), 500


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
        
        cursor.execute("SELECT CURRENT_DATE - INTERVAL '%s months' AS fecha", (periodo_meses,))
        row_fecha = cursor.fetchone()
        fecha_limite = row_fecha['fecha']
        
        # Obtenemos TODOS los servicios que cuentan para esta regla
        cursor.execute("SELECT servicio_id FROM loyalty_rule_services WHERE loyalty_rule_id = %s", (rule_id,))
        rows = cursor.fetchall()
        
        target_service_ids = [r['servicio_id'] for r in rows] # Lista de IDs
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
            WHERE v.cliente_receptor_id = %s 
              AND vi.servicio_id IN %s
              AND v.fecha_venta >= %s
              AND v.estado != 'Anulada'
              AND (vi.loyalty_consumption_group_id IS NULL OR vi.loyalty_consumption_group_id = '')
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

@marketing_bp.route('/fix-db-schema')
def fix_db_schema():
    db = get_db()
    try:
        with db.cursor() as cursor:
            # 1. Add puntos_acumulados column
            cursor.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS puntos_acumulados INTEGER DEFAULT 0")
            
            # 2. Create puntos_historial table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS puntos_historial (
                    id SERIAL PRIMARY KEY,
                    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
                    venta_id INTEGER REFERENCES ventas(id) ON DELETE SET NULL,
                    monto_puntos INTEGER NOT NULL,
                    tipo_transaccion VARCHAR(20) NOT NULL,
                    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    descripcion TEXT
                );
            """)

            # 3. Create packages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS packages (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 4. Create package_items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS package_items (
                    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
                    service_id INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (package_id, service_id)
                );
            """)
            
            # 4.1. Add description to packages
            cursor.execute("ALTER TABLE packages ADD COLUMN IF NOT EXISTS description TEXT;")

            # 5. Add package_id to gift_cards table
            cursor.execute("""
                ALTER TABLE gift_cards 
                ADD COLUMN IF NOT EXISTS package_id INTEGER REFERENCES packages(id) ON DELETE SET NULL;
            """)

            db.commit()
            return "Schema fixed successfully: puntos_acumulados, puntos_historial, packages, and package_items created/updated. <a href='/marketing/paquetes'>Go to Packages</a>", 200
    except Exception as e:
        db.rollback()
        return f"Error: {e}", 500

# ==============================================================================
# 5. GESTIÓN DE PAQUETES
# ==============================================================================

@marketing_bp.route('/paquetes', methods=['GET'])
@login_required
def listar_paquetes():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM packages ORDER BY name")
        paquetes = cursor.fetchall()
    return render_template('marketing/lista_paquetes.html', paquetes=paquetes)

@marketing_bp.route('/paquetes/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_paquete():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        description = request.form.get('description')
        service_ids = request.form.getlist('service_ids') # Multi-select
        
        try:
            with db.cursor() as cursor:
                # 1. Create Package
                cursor.execute("""
                    INSERT INTO packages (name, price, description, is_active)
                    VALUES (%s, %s, %s, TRUE) RETURNING id
                """, (name, price, description))
                package_id = cursor.fetchone()[0]
                
                # 2. Add Items
                for sid in service_ids:
                    # Default quantity 1 for simplification in UI for now
                    cursor.execute("""
                        INSERT INTO package_items (package_id, service_id, quantity)
                        VALUES (%s, %s, 1)
                    """, (package_id, sid))
                    
                db.commit()
                flash("Paquete creado exitosamente.", "success")
                return redirect(url_for('marketing.listar_paquetes'))
        except Exception as e:
            db.rollback()
            flash(f"Error creando paquete: {e}", "danger")
            
    # GET: Load services for select
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
        servicios = cursor.fetchall()
        
    return render_template('marketing/crear_paquete.html', servicios=servicios)

@marketing_bp.route('/paquetes/editar/<int:package_id>', methods=['GET', 'POST'])
@login_required
def editar_paquete(package_id):
    db = get_db()
    
    # Check existence
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM packages WHERE id = %s", (package_id,))
        package = cursor.fetchone()
        
    if not package:
        flash("Paquete no encontrado.", "danger")
        return redirect(url_for('marketing.listar_paquetes'))

    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        description = request.form.get('description')
        service_ids = request.form.getlist('service_ids')
        
        try:
            with db.cursor() as cursor:
                # 1. Update Package
                cursor.execute("""
                    UPDATE packages SET name = %s, price = %s, description = %s WHERE id = %s
                """, (name, price, description, package_id))
                
                # 2. Update Items (Delete all and re-insert)
                cursor.execute("DELETE FROM package_items WHERE package_id = %s", (package_id,))
                
                for sid in service_ids:
                    cursor.execute("""
                        INSERT INTO package_items (package_id, service_id, quantity)
                        VALUES (%s, %s, 1)
                    """, (package_id, sid))
                    
                db.commit()
                flash("Paquete actualizado exitosamente.", "success")
                return redirect(url_for('marketing.listar_paquetes'))
        except Exception as e:
            db.rollback()
            flash(f"Error actualizando paquete: {e}", "danger")
    
    # GET: Load services and current items
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT id, nombre, precio FROM servicios WHERE activo = TRUE ORDER BY nombre")
        servicios = cursor.fetchall()
        
        cursor.execute("SELECT service_id FROM package_items WHERE package_id = %s", (package_id,))
        current_items = [row['service_id'] for row in cursor.fetchall()]
        
    return render_template('marketing/crear_paquete.html', 
                           package=package, 
                           servicios=servicios, 
                           selected_service_ids=current_items)

@marketing_bp.route('/paquetes/toggle-activo/<int:package_id>', methods=['POST'])
@login_required
def toggle_activo_paquete(package_id):
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("UPDATE packages SET is_active = NOT is_active WHERE id = %s", (package_id,))
            db.commit()
            flash("Estado del paquete actualizado.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error cambiando estado: {e}", "danger")
    return redirect(url_for('marketing.listar_paquetes'))

@marketing_bp.route('/paquetes/eliminar/<int:package_id>', methods=['POST'])
@login_required
def eliminar_paquete(package_id):
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("DELETE FROM packages WHERE id = %s", (package_id,))
            db.commit()
            flash("Paquete eliminado permanentemente.", "success")
    except Exception as e:
        db.rollback()
        # Constraint error handling helpful if linked
        flash(f"Error eliminando paquete (puede estar en uso): {e}", "danger")
    return redirect(url_for('marketing.listar_paquetes'))

# ==============================================================================
# 4. GESTIÓN DE GIFT CARDS
# ==============================================================================

@marketing_bp.route('/gift-cards', methods=['GET'])
@login_required
def listar_gift_cards():
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""
                SELECT gc.*, p.name as package_name 
                FROM gift_cards gc
                LEFT JOIN packages p ON gc.package_id = p.id
                ORDER BY gc.created_at DESC
            """)
            gift_cards = cursor.fetchall()
            
        # Check for images
        static_folder = current_app.static_folder
        for gc in gift_cards:
            filename = f"gift_card_{gc['code']}.jpg"
            filepath = os.path.join(static_folder, 'img', 'gift_cards', filename)
            if os.path.exists(filepath):
                gc['image_url'] = url_for('static', filename=f'img/gift_cards/{filename}')
            else:
                gc['image_url'] = None
                
        return render_template('marketing/lista_gift_cards.html', gift_cards=gift_cards)
    except Exception as e:
        flash(f"Error listando Gift Cards: {e}", "danger")
        return redirect(url_for('marketing.index_marketing_placeholder')) # Fallback or index

@marketing_bp.route('/gift-cards/download-pdf/<code>')
@login_required
def download_gift_card_pdf(code):
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""
                SELECT gc.*, p.name as package_name 
                FROM gift_cards gc
                LEFT JOIN packages p ON gc.package_id = p.id
                WHERE gc.code = %s
            """, (code,))
            gc = cursor.fetchone()
            
        if not gc:
            flash("Gift Card no encontrada.", "danger")
            return redirect(url_for('marketing.listar_gift_cards'))
            
        # Prepare data for PDF
        package_name = gc['package_name']
        services_text = None
        description = None
        dedication = gc.get('dedicatoria')
        
        if package_name:
             # Fetch services if package
             with db.cursor() as cursor:
                # Get Description
                cursor.execute("SELECT description FROM packages WHERE id = %s", (gc['package_id'],))
                row_desc = cursor.fetchone()
                if row_desc:
                    description = row_desc[0]

                # Get Services (Still good to have as fallback or if user wants both later)
                cursor.execute("""
                    SELECT s.nombre 
                    FROM package_items pi
                    JOIN servicios s ON pi.service_id = s.id
                    WHERE pi.package_id = %s
                """, (gc['package_id'],))
                srv_rows = cursor.fetchall()
                if srv_rows:
                    services_text = " • ".join([r[0] for r in srv_rows])

        # Generate PDF
        pdf_path = generate_gift_card_pdf(
            code=gc['code'],
            amount=gc['initial_amount'],
            recipient_name=gc['recipient_name'],
            from_name=gc['purchaser_name'], # Assuming purchaser is "From"
            package_name=package_name,
            services_text=services_text,
            expiration_date=gc['expiration_date'],
            description=description,
            dedication=dedication
        )
        
        if pdf_path and os.path.exists(pdf_path):
            return send_file(pdf_path, as_attachment=True, download_name=f"GiftCard_{code}.pdf")
        else:
             flash("Error generando el PDF.", "danger")
             return redirect(url_for('marketing.listar_gift_cards'))

    except Exception as e:
        flash(f"Error descargando PDF: {e}", "danger")
        return redirect(url_for('marketing.listar_gift_cards'))

# ==============================================================================
# 5. EXTERNAL REQUESTS (LANDING PAGE)
# ==============================================================================

@marketing_bp.route('/api/external/gift-card-request', methods=['POST'])
def external_gift_card_request():
    """
    Endpoint for Landing Page form submissions.
    Currently creates a Gift Card in 'activa' status (or pending implementation).
    Returns JSON with PDF download URL or status.
    """
    # Simple security check (CORS should be handled at app level or here)
    # response.headers.add("Access-Control-Allow-Origin", "*") 
    
    data = request.form
    
    purchaser_name = data.get('purchaser_name')
    recipient_name = data.get('recipient_name')
    email = data.get('email') # Check if we have this
    selection_type = data.get('selection_type', 'amount')
    
    amount = 0
    package_id = None
    package_name = None
    
    db = get_db()
    
    try:
        code = generate_gift_card_code(db)
        
        if selection_type == 'package':
            package_id = data.get('package_id')
            with db.cursor() as cursor:
                cursor.execute("SELECT name, price FROM packages WHERE id = %s", (package_id,))
                res = cursor.fetchone()
                if res:
                    package_name = res[0]
                    amount = res[1]
                else:
                    return jsonify({'success': False, 'message': 'Paquete inválido'}), 400
        else:
            amount = float(data.get('amount', 0))
            if amount <= 0:
                 return jsonify({'success': False, 'message': 'Monto inválido'}), 400

        # Create Gift Card
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO gift_cards (code, initial_amount, current_balance, status, purchaser_name, recipient_name, package_id)
                VALUES (%s, %s, %s, 'activa', %s, %s, %s)
            """, (code, amount, amount, purchaser_name, recipient_name, package_id))
            db.commit()
            
        # Generate PDF immediately for response
        # We need services text if package
        services_text = None
        if package_id:
             with db.cursor() as cursor:
                cursor.execute("""
                    SELECT s.nombre 
                    FROM package_items pi
                    JOIN servicios s ON pi.service_id = s.id
                    WHERE pi.package_id = %s
                """, (package_id,))
                srv_rows = cursor.fetchall()
                if srv_rows:
                    services_text = " • ".join([r[0] for r in srv_rows])

        pdf_path = generate_gift_card_pdf(
            code=code,
            amount=amount,
            recipient_name=recipient_name,
            from_name=purchaser_name,
            package_name=package_name,
            services_text=services_text
        )
        
        # In a real scenario, we might email this PDF to 'email'
        
        # Return success with download link (requires session auth usually, but we might need a public token link)
        # For now, we will just return success and the code.
        
        return jsonify({
            'success': True,
            'message': 'Solicitud recibida correctamente.',
            'code': code,
            'note': 'Gift Card creada. Contacte para pago.'
        })

    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# Helper para generar códigos
def generate_gift_card_code(db):
    """
    Genera un código único en formato JV-XXX-NNNN
    Ejemplo: JV-FEB-4921
    """
    # Intenta generar un código único hasta 10 veces
    for _ in range(10):
        # 3 letras mayúsculas aleatorias (Ej. ABC)
        letters = ''.join(random.choices(string.ascii_uppercase, k=3))
        # 4 números aleatorios
        numbers = ''.join(random.choices(string.digits, k=4))
        
        code = f"JV-{letters}-{numbers}"
        
        # Verificar unicidad
        with db.cursor() as cursor:
            cursor.execute("SELECT 1 FROM gift_cards WHERE code = %s", (code,))
            if not cursor.fetchone():
                return code
                
    # Fallback muy improbable si falla 10 veces
    import uuid
    return f"JV-AUTO-{str(uuid.uuid4())[:4].upper()}"

@marketing_bp.route('/gift-cards/nueva', methods=['GET', 'POST'])
@login_required
def nueva_gift_card():
    db = get_db()
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        purchaser = request.form.get('purchaser_name', '').strip()
        recipient = request.form.get('recipient_name', '').strip()
        
        # Logic for selection type
        selection_type = request.form.get('selection_type') # 'amount' or 'package'
        
        amount = 0
        package_id = None
        
        package_name = None
        services_text = None

        if selection_type == 'package':
            package_id = request.form.get('package_id')
            if not package_id:
                flash("Debes seleccionar un paquete.", "danger")
                return redirect(url_for('marketing.nueva_gift_card'))
                
            # Get package details
            with db.cursor() as cursor:
                cursor.execute("SELECT name, price FROM packages WHERE id = %s", (package_id,))
                res = cursor.fetchone()
                if res:
                    package_name = res[0]
                    amount = res[1]
                
                # Fetch Service Names
                cursor.execute("""
                    SELECT s.nombre 
                    FROM package_items pi
                    JOIN servicios s ON pi.service_id = s.id
                    WHERE pi.package_id = %s
                """, (package_id,))
                srv_rows = cursor.fetchall()
                if srv_rows:
                    services_text = " • ".join([r[0] for r in srv_rows])
        else:
            amount = request.form.get('amount')
            if not amount:
                 flash("Debes ingresar un monto.", "danger")
                 return redirect(url_for('marketing.nueva_gift_card'))

        expiration = request.form.get('expiration_date') or None
        dedication = request.form.get('dedicatoria', '').strip()
        
        # Auto-generate code if empty
        if not code:
            code = generate_gift_card_code(db)
        
        try:
            with db.cursor() as cursor:
                # Check duplicate (only relevant if manual code was entered)
                cursor.execute("SELECT id FROM gift_cards WHERE code = %s", (code,))
                if cursor.fetchone():
                    flash("El código de Gift Card ya existe. Intenta con otro.", "warning")
                    return redirect(url_for('marketing.nueva_gift_card'))
                
                cursor.execute("""
                    INSERT INTO gift_cards 
                    (code, initial_amount, current_balance, status, expiration_date, purchaser_name, recipient_name, package_id, dedicatoria)
                    VALUES (%s, %s, %s, 'activa', %s, %s, %s, %s, %s)
                """, (code, amount, amount, expiration, purchaser, recipient, package_id, dedication))
                
                db.commit()

                # Generate Image with Package details if applicable
                # Note: Generate image might typically usage 'description' logic in future too
                image_url = generate_gift_card_image(code, amount, recipient, package_name=package_name, services_text=services_text)
                
                flash(f"Gift Card creada exitosamente. <a href='{image_url}' target='_blank' class='btn btn-sm btn-light ms-2'><i class='fas fa-download'></i> Descargar Tarjeta</a>", "success")
                return redirect(url_for('marketing.listar_gift_cards'))
                
        except Exception as e:
            db.rollback()
            flash(f"Error creando Gift Card: {e}", "danger")
            
    # GET Request: Fetch packages for dropdown
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM packages WHERE is_active = TRUE ORDER BY name")
        packages = cursor.fetchall()
            
    return render_template('marketing/crear_gift_card.html', packages=packages)
