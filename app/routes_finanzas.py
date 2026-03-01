from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from calendar import monthrange
from .db import get_db


# ... el resto del código sigue igual ...

# Definimos el "Blueprint" (es como un mini-módulo dentro de la app)
finanzas_bp = Blueprint('finanzas', __name__, url_prefix='/finanzas')

# --- FUNCIÓN AUXILIAR (Lógica de cálculo) ---
def _calcular_produccion_mes_actual(cursor, empleado_id, tipo_salario, sueldo_basico=0):
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    
    produccion = 0.00

    if tipo_salario == 'Fijo_Recepcion':
        produccion = float(sueldo_basico or 0)

    elif tipo_salario in ['Comisionista', 'Mixto_Instructor']:
        # CORRECCIÓN AQUÍ: Agregamos "AS total" para poder leerlo por nombre
        cursor.execute("""
            SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
            FROM venta_items vi
            JOIN ventas v ON vi.venta_id = v.id
            WHERE v.empleado_id = %s 
              AND v.fecha_venta >= %s 
              AND v.estado != 'Anulada'
        """, (empleado_id, inicio_mes))
        
        result = cursor.fetchone()
        
        # CORRECCIÓN AQUÍ: Usamos result['total'] en vez de result[0]
        # (Esto detecta automáticamente si el cursor es Dict o Tupla)
        if result:
            if isinstance(result, dict):
                produccion = float(result['total'])
            else:
                produccion = float(result[0])
        else:
            produccion = 0.00
            
    return produccion

# --- RUTAS (ENDPOINTS) ---


# ==============================================================================
# LÓGICA DE CÁLCULO MULTI-ROL (Cajero, Barbero, Educador)
# ==============================================================================
def _calcular_metricas_fondo(cursor, empleado_id, tipo_salario, sueldo_basico=0, porcentaje_prod_empleado=0):
    
    # Retorna dos valores:
    # 1. progreso_meta: Cuánto ha logrado para llenar la barra.
    # 2. base_calculo: Sobre qué monto se calcula el 5% del fondo.
    
    hoy = date.today()
    inicio_mes = hoy.replace(day=1)
    
    progreso_meta = 0.00
    base_calculo = 0.00

    # --- 1. DATOS COMUNES: VENTA DE PRODUCTOS ---
    # Necesario para Cajeros y Barberos
    cursor.execute("""
        SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
        FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
        JOIN productos p ON vi.producto_id = p.id
        WHERE v.empleado_id = %s AND v.fecha_venta >= %s AND v.estado != 'Anulada'
    """, (empleado_id, inicio_mes))
    venta_productos = float(cursor.fetchone()['total'])
    comision_productos = venta_productos * (float(porcentaje_prod_empleado) / 100)

    # --- 2. DATOS COMUNES: VENTA DE SERVICIOS (BARBERÍA) ---
    cursor.execute("""
        SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
        FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
        JOIN servicios s ON vi.servicio_id = s.id
        WHERE v.empleado_id = %s AND v.fecha_venta >= %s AND v.estado != 'Anulada'
    """, (empleado_id, inicio_mes))
    produccion_servicios = float(cursor.fetchone()['total'])


    # === CASO A: CAJERO (Meta = Comisiones Productos | Fondo = Sueldo + Comisiones) ===
    if tipo_salario == 'Cajero_Ventas':
        # Meta: "Se considerará la suma de la comisión"
        progreso_meta = comision_productos 
        
        # Fondo: "Porcentaje en base a su sueldo + comision venta productos"
        base_calculo = float(sueldo_basico) + comision_productos


    # === CASO B: EDUCADOR (Meta/Fondo = Servicios + 30% Academia) ===
    elif tipo_salario == 'Mixto_Instructor':
        # 1. Calcular Comisiones de Academia (30% de mensualidades)
        cursor.execute("""
            SELECT COALESCE(SUM(comision_instructor), 0) as total_edu
            FROM ingresos_academia
            WHERE empleado_instructor_id = %s AND fecha_pago >= %s
        """, (empleado_id, inicio_mes))
        comision_educacion = float(cursor.fetchone()['total_edu'])
        
        # Meta y Fondo: "Suma de comisión educador + producción barbero"
        # Nota: Asumimos que "producción barbero" se refiere al total vendido en servicios
        total_mixto = produccion_servicios + comision_educacion
        
        progreso_meta = total_mixto
        base_calculo = total_mixto


    # === CASO C: BARBERO ESTÁNDAR (Meta/Fondo = Producción Total) ===
    else: # 'Comisionista'
        # Asumimos que su meta es su producción total (Servicios + Productos)
        total_prod = produccion_servicios # + venta_productos (según tu regla anterior)
        
        progreso_meta = total_prod
        # Para barberos, el fondo suele calcularse sobre lo que ellos produjeron
        base_calculo = total_prod 

    return progreso_meta, base_calculo


@finanzas_bp.route('/api/fondo-lealtad', methods=['GET'])
@login_required
def dashboard_fondo_lealtad():
    empleado_id = getattr(current_user, 'empleado_id', None)
    
    # Fallback si no está linkeado en sesión
    if not empleado_id:
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM empleados WHERE email = %s", (current_user.email,))
            res = cursor.fetchone()
            if res: empleado_id = res[0]
            else: return jsonify({'error': 'Usuario no vinculado'}), 400

    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Obtener Configuración Global y Empleado
            cursor.execute("SELECT porcentaje_fondo_global FROM configuracion_sistema LIMIT 1")
            conf = cursor.fetchone()
            porcentaje_global = float(conf['porcentaje_fondo_global']) if conf else 5.00

            cursor.execute("""
                SELECT meta_activacion_mensual, porcentaje_fondo, saldo_fondo_acumulado, 
                       tipo_salario, sueldo_fijo_mensual, porcentaje_productos, nombres
                FROM empleados WHERE id = %s
            """, (empleado_id,))
            emp = cursor.fetchone()

            if not emp: return jsonify({'error': 'Empleado no encontrado'}), 404

            # Preferencia: Si el empleado tiene un % específico, úsalo. Si no, usa el Global.
            porcentaje_aplicar = float(emp['porcentaje_fondo']) if emp['porcentaje_fondo'] else porcentaje_global
            meta = float(emp['meta_activacion_mensual'] or 0)
            
            # 2. CALCULAR MÉTRICAS (Usando la nueva función inteligente)
            progreso_actual, base_para_fondo = _calcular_metricas_fondo(
                cursor, 
                empleado_id, 
                emp['tipo_salario'], 
                emp['sueldo_fijo_mensual'] or 0,
                emp['porcentaje_productos'] or 0
            )
            
            # 3. Proyección Dinero
            aporte_proyectado = base_para_fondo * (porcentaje_aplicar / 100)
            
            # 4. Porcentaje Barra (Tope 100%)
            barra_porcentaje = min(100, (progreso_actual / meta) * 100) if meta > 0 else 100

            # 5. Gamificación Visual
            estado_visual = {}
            if progreso_actual >= meta:
                estado_visual = {
                    'color': '#28a745', 'icono': '🎉', 'titulo': '¡BONO ACTIVADO!',
                    'mensaje': f'Fondo asegurado este mes: S/ {aporte_proyectado:.2f}', 'clase_css': 'bg-success'
                }
            elif progreso_actual >= (meta * 0.7):
                faltante = meta - progreso_actual
                estado_visual = {
                    'color': '#ffc107', 'icono': '🔥', 'titulo': '¡Ya casi!',
                    'mensaje': f'Te falta generar S/ {faltante:.2f} para desbloquear.', 'clase_css': 'bg-warning'
                }
            else:
                faltante = meta - progreso_actual
                estado_visual = {
                    'color': '#dc3545', 'icono': '💪', 'titulo': 'Tú puedes',
                    'mensaje': f'Meta restante: S/ {faltante:.2f}', 'clase_css': 'bg-danger'
                }

            # 6. Historial
            cursor.execute("""
                SELECT fecha, tipo_movimiento, monto, motivo 
                FROM movimientos_fondo 
                WHERE empleado_id = %s 
                ORDER BY fecha DESC LIMIT 10
            """, (empleado_id,))
            historial = cursor.fetchall()
            
            return jsonify({
                'resumen': {
                    'saldo_total_acumulado': float(emp['saldo_fondo_acumulado']),
                    'aporte_mes_proyectado': aporte_proyectado if progreso_actual >= meta else 0,
                    'meta_objetivo': meta,
                    'progreso_actual_valor': progreso_actual, # Valor numérico para mostrar "Llevas X"
                    'base_calculo_real': base_para_fondo # Dato informativo
                },
                'gamificacion': {
                    'progreso_porcentaje': barra_porcentaje,
                    **estado_visual
                },
                'historial': [dict(h) for h in historial]
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# --- HELPER: Obtener Porcentaje Configurado (Jerárquico) ---
def _get_porcentaje_fondo(cursor, anio, mes, empleado_id=None):
    # 1. Específico del Colaborador para ese Mes
    if empleado_id:
        cursor.execute("""
            SELECT porcentaje FROM configuracion_fondo_mensual 
            WHERE anio=%s AND mes=%s AND empleado_id=%s
        """, (anio, mes, empleado_id))
        res = cursor.fetchone()
        if res: return float(res[0]) # psycopg2 tuple access or RealDictCursor check needed?
        # Note: If cursor_factory is RealDictCursor, res is dict. 
        # But this helper might be called with different cursors. 
        # Safe access:
        if res and isinstance(res, dict): return float(res['porcentaje'])
        if res and isinstance(res, tuple): return float(res[0])
    
    # 2. Global para ese Mes
    cursor.execute("""
        SELECT porcentaje FROM configuracion_fondo_mensual 
        WHERE anio=%s AND mes=%s AND empleado_id IS NULL
    """, (anio, mes))
    res = cursor.fetchone()
    if res:
        if isinstance(res, dict): return float(res['porcentaje'])
        if isinstance(res, tuple): return float(res[0])

    # 3. Default del Sistema (Global General) o 2%
    cursor.execute("SELECT porcentaje_fondo_global FROM configuracion_sistema LIMIT 1")
    conf = cursor.fetchone()
    # Si es Dict
    if conf and isinstance(conf, dict): return float(conf['porcentaje_fondo_global'])
    # Si es Tuple
    if conf and isinstance(conf, tuple): return float(conf[0])
    
    return 2.00 # Default solicitado por usuario

def _ensure_fondo_table_exists(cursor):
    """Crea la tabla de configuración si no existe (Lazy Init para Producción)"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_fondo_mensual (
            anio INT NOT NULL,
            mes INT NOT NULL,
            empleado_id INT DEFAULT NULL,
            porcentaje DECIMAL(5,2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Unique Index Global
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_global 
        ON configuracion_fondo_mensual (anio, mes) 
        WHERE empleado_id IS NULL;
    """)
    # Unique Index Empleado
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fondo_conf_empleado 
        ON configuracion_fondo_mensual (anio, mes, empleado_id) 
        WHERE empleado_id IS NOT NULL;
    """)


# --- HELPER: Calcular Producción en Rango ---
def _calcular_produccion_rango(cursor, empleado_id, tipo_salario, f_inicio, f_fin, sueldo_basico=0):
    produccion = 0.00

    if tipo_salario == 'Fijo_Recepcion':
        produccion = float(sueldo_basico or 0)

    elif tipo_salario in ['Comisionista', 'Mixto_Instructor']:
        cursor.execute("""
            SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
            FROM venta_items vi
            JOIN ventas v ON vi.venta_id = v.id
            WHERE v.empleado_id = %s 
              AND v.fecha_venta BETWEEN %s AND %s
              AND v.estado != 'Anulada'
        """, (empleado_id, f_inicio, f_fin))
        
        result = cursor.fetchone()
        if result:
            # Safe access
            val = result['total'] if isinstance(result, dict) else result[0]
            produccion = float(val)
    
    return produccion

@finanzas_bp.route('/fondo/configurar', methods=['POST'])
@login_required
def configurar_porcentaje_fondo():
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        return jsonify({'error': 'No autorizado'}), 403

    anio = request.form.get('anio')
    mes = request.form.get('mes')
    porcentaje = request.form.get('porcentaje') # Global del mes
    
    # Opcional: Configuración por empleado (Array/JSON o inputs individuales)
    # Para simplicidad, este endpoint puede manejar ambos si se envia 'empleado_id'
    empleado_id = request.form.get('empleado_id') # Si viene vacio es Global

    if not anio or not mes or not porcentaje:
        return jsonify({'error': 'Faltan datos'}), 400

    try:
        db = get_db()
        with db.cursor() as cursor:
            # Check/Create table first (Fixes Production missing table issue)
            _ensure_fondo_table_exists(cursor)

            # Upsert Logic (Postgres 9.5+)
            # ON CONFLICT update.
            # Convert empty string to None for empleado_id
            emp_id_val = int(empleado_id) if (empleado_id and empleado_id != 'null') else None
            
            # Check existenc
            if emp_id_val:
                query_check = "SELECT 1 FROM configuracion_fondo_mensual WHERE anio=%s AND mes=%s AND empleado_id=%s"
                params_check = (anio, mes, emp_id_val)
            else:
                query_check = "SELECT 1 FROM configuracion_fondo_mensual WHERE anio=%s AND mes=%s AND empleado_id IS NULL"
                params_check = (anio, mes)

            cursor.execute(query_check, params_check)
            exists = cursor.fetchone()

            if exists:
                if emp_id_val:
                    cursor.execute("""
                        UPDATE configuracion_fondo_mensual SET porcentaje=%s, updated_at=NOW()
                        WHERE anio=%s AND mes=%s AND empleado_id=%s
                    """, (porcentaje, anio, mes, emp_id_val))
                else:
                    cursor.execute("""
                        UPDATE configuracion_fondo_mensual SET porcentaje=%s, updated_at=NOW()
                        WHERE anio=%s AND mes=%s AND empleado_id IS NULL
                    """, (porcentaje, anio, mes))
            else:
                cursor.execute("""
                    INSERT INTO configuracion_fondo_mensual (anio, mes, empleado_id, porcentaje)
                    VALUES (%s, %s, %s, %s)
                """, (anio, mes, emp_id_val, porcentaje))
            
            db.commit()
            return jsonify({'mensaje': 'Configuración guardada'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@finanzas_bp.route('/fondo/generar-cierre', methods=['POST'])
@login_required
def generar_cierre_fondo_manual():
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        return jsonify({'error': 'No autorizado'}), 403

    data = request.json
    anio = int(data.get('anio'))
    mes = int(data.get('mes'))
    
    # 1. Definir rango de fechas para ESE mes
    import calendar
    last_day = calendar.monthrange(anio, mes)[1]
    f_inicio = date(anio, mes, 1)
    f_fin = date(anio, mes, last_day)

    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 2. Obtener empleados activos
            cursor.execute("SELECT id, meta_activacion_mensual, tipo_salario, nombres, apellidos FROM empleados WHERE activo=TRUE")
            empleados = cursor.fetchall()
            
            resumen_generado = []

            for emp in empleados:
                # 3. Calcular Producción para ese mes específico
                produccion = _calcular_produccion_rango(cursor, emp['id'], emp['tipo_salario'], f_inicio, f_fin)
                
                # 4. Obtener Porcentaje Configurado (Time Travel Logic)
                pct = _get_porcentaje_fondo(cursor, anio, mes, emp['id'])
                
                meta = float(emp['meta_activacion_mensual'] or 0)
                
                # REGLA: ¿Cumplió meta?
                if produccion >= meta:
                    monto_fondo = produccion * (pct / 100)
                    
                    # 5. Insertar o Actualizar el Fondo
                    # IMPORTANTE: Para evitar duplicados si se corre 2 veces el mismo mes,
                    # deberíamos borrar primero el 'Aporte_Mensual' de ese mes o hacer un upsert inteligente.
                    # Asumiremos que el usuario sabe lo que hace, o borramos preventivamente movimientos de tipo 'Aporte_Mensual' en ese rango?
                    # Riesgoso borrar historial. Mejor verificamos si ya existe.
                    
                    cursor.execute("""
                        SELECT id FROM movimientos_fondo 
                        WHERE empleado_id=%s AND tipo_movimiento='Aporte_Mensual' 
                        AND fecha BETWEEN %s AND %s
                    """, (emp['id'], f_inicio, f_fin))
                    ya_existe = cursor.fetchone()
                    
                    if not ya_existe:
                        # A. Registrar Movimiento (Historial interno Fondo)
                        cursor.execute("""
                            INSERT INTO movimientos_fondo (empleado_id, tipo_movimiento, monto, motivo, fecha)
                            VALUES (%s, 'Aporte_Mensual', %s, %s, %s)
                        """, (emp['id'], monto_fondo, f'Cierre Mes {mes}/{anio} - {pct}%', f_fin))
                        
                        # B. Actualizar Saldo Acumulado Empleado
                        cursor.execute("UPDATE empleados SET saldo_fondo_acumulado = saldo_fondo_acumulado + %s WHERE id=%s", (monto_fondo, emp['id']))
                        
                        # C. Registrar Ajuste de Pago (Para reporte Producción)
                        # Tipo 'Fondo Fidelidad' para que salga en la columna "Fondo Fidelidad"
                        # Lo registramos con fecha fin de mes para que salga en reportes de ese mes.
                        cursor.execute("""
                            INSERT INTO ajustes_pago (empleado_id, fecha, tipo, monto, descripcion)
                            VALUES (%s, %s, 'Fondo Fidelidad', %s, %s)
                        """, (emp['id'], f_fin, -monto_fondo, f'Retención Fondo Fidelidad {mes}/{anio}')) 
                        # Nota: Monto negativo porque es descuento/retención? 
                        # En reportes: ABS(SUM(monto)). Aqui lo guardo negativo para consistencia contable (sale de su "bolsillo" hacia el fondo).
                        
                        resumen_generado.append(f"{emp['nombres']}: S/ {monto_fondo:.2f} ({pct}%)")
                    else:
                        resumen_generado.append(f"{emp['nombres']}: Ya procesado.")

                else:
                    resumen_generado.append(f"{emp['nombres']}: No llegó a meta ({produccion} < {meta})")

            db.commit()
            return jsonify({'mensaje': 'Cierre procesado correctamente', 'detalle': resumen_generado})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




import json

# ... (imports existing) ...

# ==============================================================================
# 1. FUNCIÓN AUXILIAR: LÓGICA DE TRAMOS (CEREBRO MATEMÁTICO)
# ==============================================================================
def _calcular_desglose_tramos(tramos, venta_pagable, acumulado_histórico_mes):
    """
    Calcula cuánto pagar por la 'venta_pagable' actual, basándose en el 
    'acumulado_histórico_mes' y una lista de 'tramos' dada.
    
    tramos espera: [{'min': 0, 'max': 4000, 'pct': 50}, ...]
    """
    desglose = []
    monto_restante_por_pagar = float(venta_pagable)
    
    # El cursor empieza donde va la producción TOTAL del mes (incluyendo lo ya pagado)
    cursor_nivel = float(acumulado_histórico_mes) 
    
    comision_total = 0.0
    
    # Ordenar tramos por monto mínimo para asegurar orden lógico
    tramos_ordenados = sorted(tramos, key=lambda x: float(x.get('min', 0)))
    
    for tramo in tramos_ordenados:
        if monto_restante_por_pagar <= 0:
            break
            
        techo_tramo = float(tramo.get('max')) if tramo.get('max') is not None else float('inf')
        piso_tramo = float(tramo.get('min', 0))
        tasa = float(tramo.get('pct', 0))
        
        # 1. ¿Este nivel ya fue superado por la producción histórica?
        if cursor_nivel >= techo_tramo:
            continue 
            
        # 2. ¿Cuánto espacio queda en este nivel?
        # El espacio es desde max(piso, cursor) hasta techo
        inicio_efectivo = max(piso_tramo, cursor_nivel)
        espacio_disponible = techo_tramo - inicio_efectivo
        
        # 3. ¿Cuánto de mi venta actual cabe aquí?
        monto_a_computar = min(monto_restante_por_pagar, espacio_disponible)
        
        if monto_a_computar > 0:
            subtotal_comision = monto_a_computar * (tasa / 100)
            desglose.append({
                'nivel': f"Tramo {piso_tramo} - {techo_tramo if techo_tramo != float('inf') else 'Inf'}",
                'tasa': tasa,
                'venta_base': monto_a_computar,
                'comision': subtotal_comision
            })
            
            comision_total += subtotal_comision
            monto_restante_por_pagar -= monto_a_computar
            cursor_nivel += monto_a_computar # Avanzamos el cursor de nivel
            
    return desglose, comision_total


# ==============================================================================
# 2. ENDPOINT: CALCULAR PLANILLA (PRELIMINAR)
# ==============================================================================
@finanzas_bp.route('/api/calcular-planilla-empleado', methods=['POST'])
@login_required
def calcular_planilla_preliminar():
    """
    Calcula el pago exacto excluyendo ventas ya pagadas y descontando adelantos no deducidos.
    """
    data = request.json
    empleado_id = data.get('empleado_id')
    f_inicio_str = data.get('fecha_inicio')
    f_fin_str = data.get('fecha_fin')

    db = get_db()
    
    try:
        f_inicio = datetime.strptime(f_inicio_str, '%Y-%m-%d').date()
        f_fin = datetime.strptime(f_fin_str, '%Y-%m-%d').date()
        
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # A. Datos Básicos
            cursor.execute("""
                SELECT id, nombres, apellidos, tipo_contrato, configuracion_comision, sueldo_base 
                FROM empleados WHERE id = %s
            """, (empleado_id,))
            empleado = cursor.fetchone()
            if not empleado: return jsonify({'error': 'Empleado no encontrado'}), 404
            
            cursor.execute("SELECT sueldo_minimo_vital FROM configuracion_sistema LIMIT 1")
            config = cursor.fetchone()
            smv = float(config['sueldo_minimo_vital']) if config else 1130.00
            
            tipo_contrato = empleado.get('tipo_contrato', 'FIJO')
            # Parsear config comision si viene como string (aunque psycopg2 con JSONB suele devolver dict)
            conf_comision = empleado.get('configuracion_comision') or {}
            if isinstance(conf_comision, str):
                try:
                    conf_comision = json.loads(conf_comision)
                except:
                    conf_comision = {}

            total_comisiones_periodo = 0.00
            detalle_final = []
            mensajes_alerta = []
            reintegro_smv_total = 0.00
            
            # B. Detectar Sub-Periodos (Cruce de Meses)
            sub_periodos = []
            if f_inicio.month == f_fin.month and f_inicio.year == f_fin.year:
                sub_periodos.append({'inicio': f_inicio, 'fin': f_fin})
            else:
                ultimo_dia_mes_1 = date(f_inicio.year, f_inicio.month, monthrange(f_inicio.year, f_inicio.month)[1])
                primer_dia_mes_2 = f_fin.replace(day=1)
                sub_periodos.append({'inicio': f_inicio, 'fin': ultimo_dia_mes_1})
                sub_periodos.append({'inicio': primer_dia_mes_2, 'fin': f_fin})
            
            # C. Procesar cada Sub-Periodo
            for periodo in sub_periodos:
                p_ini = periodo['inicio']
                p_fin = periodo['fin']
                
                # 1. VENTA PAGABLE (Solo lo que NO tiene 'pago_nomina_id')
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s 
                      AND v.fecha_venta BETWEEN %s AND %s 
                      AND v.estado != 'Anulada'
                      AND v.pago_nomina_id IS NULL 
                """, (empleado_id, p_ini, p_fin))
                venta_pagable = float(cursor.fetchone()['total'])
                
                # 2. ACUMULADO HISTÓRICO DEL MES (Para nivel de escala o meta)
                inicio_de_ese_mes = p_ini.replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s 
                      AND v.fecha_venta >= %s AND v.fecha_venta < %s 
                      AND v.estado != 'Anulada'
                """, (empleado_id, inicio_de_ese_mes, p_ini))
                acumulado_histórico = float(cursor.fetchone()['total'])
                
                comision_sub = 0.00
                desglose_tramos = []
                
                if venta_pagable > 0:
                    # --- LÓGICA SEGÚN TIPO DE CONTRATO ---
                    if tipo_contrato == 'FIJO':
                        # Sueldo fijo no gana comisión por producción (salvo bonos manuales)
                        comision_sub = 0.00
                        desglose_tramos.append({'nivel': 'Contrato Fijo', 'tasa': 0, 'venta_base': venta_pagable, 'comision': 0})
                        
                    elif tipo_contrato == 'MIXTO':
                        meta = float(conf_comision.get('meta', 0))
                        pct_exceso = float(conf_comision.get('porcentaje', 0))
                        
                        # Definir trampo simple: Hasta meta = 0%, Desde meta = pct_exceso%
                        tramos_mixtos = [
                            {'min': 0, 'max': meta, 'pct': 0},
                            {'min': meta, 'max': None, 'pct': pct_exceso}
                        ]
                        desglose_tramos, comision_sub = _calcular_desglose_tramos(tramos_mixtos, venta_pagable, acumulado_histórico)
                        
                    elif tipo_contrato in ('ESCALONADA', 'FIJO_ESCALONADA'):
                        # Obtener tramos de la configuración del empleado
                        tramos_config = conf_comision.get('tramos', [])
                        # Si no hay configuración, usar un default seguro (0%) o un fallback
                        if not tramos_config:
                             tramos_config = [{'min': 0, 'max': None, 'pct': 0}] # Sin comisión si no se configuró
                        
                        desglose_tramos, comision_sub = _calcular_desglose_tramos(tramos_config, venta_pagable, acumulado_histórico)

                    total_comisiones_periodo += comision_sub
                    
                    detalle_final.append({
                        'fechas': f"{p_ini.strftime('%d/%m')} al {p_fin.strftime('%d/%m')}",
                        'venta_nueva': venta_pagable,
                        'acumulado_previo': acumulado_histórico,
                        'tipo_calculo': tipo_contrato,
                        'desglose': desglose_tramos
                    })

                # 4. Validación SMV (Solo fin de mes Y si es Escalonada/Mixta que dependa solo de prod)
                # En Fijo se asume que gana > SMV o se ajusta en sueldo base.
                # En Escalonada es donde dice la ley que no puede ganar menos del mínimo si cumple horario.
                ultimo_dia_del_mes_actual = date(p_ini.year, p_ini.month, monthrange(p_ini.year, p_ini.month)[1])
                
                if p_fin == ultimo_dia_del_mes_actual and tipo_contrato == 'ESCALONADA':
                    # Calcular cuánto ganó en TOTAL de comisiones en el mes (lo pagado + lo actual)
                    # Nota: Esto es complejo porque requeriría sumar las comisiones YA PAGADAS.
                    # Simplificación: Recalcular comisión teórica sobre la Producción Total del Mes
                    total_prod_mes = acumulado_histórico + venta_pagable
                    
                    # Usamos la misma función de tramos para ver cuánto COMISIONARÍA por todo el mes
                    tramos_config = conf_comision.get('tramos', [])
                    _, comision_teorica_total_mes = _calcular_desglose_tramos(tramos_config, total_prod_mes, 0)
                    
                    if comision_teorica_total_mes < smv:
                        diferencia = smv - comision_teorica_total_mes
                        if diferencia > 0:
                            # OJO: Aquí habría que ver si YA se le pagó algún reintegro antes, 
                            # pero asumimos que el reintegro se hace al cierre de mes.
                            reintegro_smv_total += diferencia
                            mensajes_alerta.append(f"⚠️ Reintegro SMV ({p_ini.strftime('%B')}): S/ {diferencia:.2f} (Comisión Real: {comision_teorica_total_mes:.2f} vs Mínimo {smv})")

            # D. DEDUCCIÓN DE ADELANTOS (Lista detallada)
            cursor.execute("""
                SELECT id, concepto as descripcion, monto, fecha 
                FROM gastos 
                WHERE empleado_beneficiario_id = %s 
                  AND fecha BETWEEN %s AND %s
                  AND deducido_en_planilla_id IS NULL 
            """, (empleado_id, f_inicio, f_fin))
            adelantos = cursor.fetchall()
            total_adelantos = sum(float(a['monto']) for a in adelantos) if adelantos else 0.0

            # E. PENALIDADES
            cursor.execute("""
                SELECT id, motivo, monto, fecha_registro as fecha
                FROM empleado_penalidades
                WHERE empleado_id = %s
                  AND fecha_registro::date BETWEEN %s AND %s
                  AND deducido_en_planilla_id IS NULL
            """, (empleado_id, f_inicio, f_fin))
            penalidades = cursor.fetchall()
            total_penalidades = sum(float(p['monto']) for p in penalidades) if penalidades else 0.0

            # F. DEUDAS / PRÉSTAMOS
            # Traemos las deudas pendientes, sin filtro de fecha porque se cobran hasta que se paguen.
            cursor.execute("""
                SELECT id, concepto, (monto_total - monto_pagado) as saldo_restante, fecha_registro as fecha
                FROM empleado_deudas
                WHERE empleado_id = %s
                  AND estado = 'Pendiente'
            """, (empleado_id,))
            deudas = cursor.fetchall()

            # G. CÁLCULO DE SUELDO BASE (Prorrateado)
            # Días en el rango consultado (inclusivo)
            dias_rango = (f_fin - f_inicio).days + 1
            sueldo_base_mensual = float(empleado.get('sueldo_base') or 0.0)
            
            sueldo_base_prorrateado = 0.0
            if tipo_contrato in ('FIJO', 'MIXTO', 'FIJO_ESCALONADA') and sueldo_base_mensual > 0:
                # Usamos 30 días como mes comercial para el prorrateo estándar
                # Si el rango consulta 30 o 31 días, se paga el mes completo
                if dias_rango >= 30:
                    sueldo_base_prorrateado = sueldo_base_mensual
                else:
                    sueldo_base_prorrateado = round((sueldo_base_mensual / 30.0) * dias_rango, 2)

            # CALCULAR AMORTIZACIÓN (Deuda)
            # Verificamos si podemos cobrar toda la deuda con el sueldo actual + comisiones
            total_deuda_a_amortizar = 0.0
            # Bruto inicial antes de deducir deudas (sí restamos adelantos y penalidades por ser del mes)
            bruto_previo_deuda = total_comisiones_periodo + reintegro_smv_total + sueldo_base_prorrateado - total_adelantos - total_penalidades
            
            deudas_amortizadas = []
            for d in deudas:
                saldo = float(d['saldo_restante'])
                cobro = min(saldo, bruto_previo_deuda) if bruto_previo_deuda > 0 else 0
                if cobro > 0:
                    deudas_amortizadas.append({
                        'id': d['id'],
                        'concepto': d['concepto'],
                        'monto_deducido': cobro,
                        'saldo_anterior': saldo
                    })
                    total_deuda_a_amortizar += cobro
                    bruto_previo_deuda -= cobro

            # H. TOTAL FINAL
            total_bruto = total_comisiones_periodo + reintegro_smv_total + sueldo_base_prorrateado
            total_neto_pagar = total_bruto - total_adelantos - total_penalidades - total_deuda_a_amortizar

            # Convertir fechas a string para el JSON
            def format_list(lst):
                for item in lst:
                    if 'fecha' in item and hasattr(item['fecha'], 'strftime'):
                        item['fecha'] = item['fecha'].strftime('%Y-%m-%d')
                return lst

            return jsonify({
                'empleado': f"{empleado['nombres']} {empleado['apellidos']}",
                'total_a_pagar': round(total_neto_pagar, 2),
                'resumen_financiero': {
                    'sueldo_base_prorrateado': sueldo_base_prorrateado,
                    'bruto_comisiones': total_comisiones_periodo,
                    'reintegro_smv': reintegro_smv_total,
                    'total_bruto': round(total_bruto, 2),
                    
                    'descuento_adelantos': total_adelantos,
                    'descuento_penalidades': total_penalidades,
                    'amortizacion_deudas': total_deuda_a_amortizar,
                    
                    'neto_a_pagar': round(total_neto_pagar, 2)
                },
                'detalle_calculo': detalle_final,
                'listado_adelantos': format_list(adelantos),
                'listado_penalidades': format_list(penalidades),
                'listado_deudas': deudas_amortizadas,
                'mensajes': mensajes_alerta
            })

    except Exception as e:
        print(f"Error planilla: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
@finanzas_bp.route('/api/guardar-planilla', methods=['POST'])
@login_required
def guardar_planilla():
    # Aquí recibirías el JSON final confirmado por el admin y harías el INSERT en la tabla 'planillas'
    # ... Lógica de INSERT ...
    return jsonify({'mensaje': 'Planilla guardada correctamente'})


# --- VISTAS HTML (PÁGINAS) ---

@finanzas_bp.route('/planilla', methods=['GET'])
@login_required
def ver_planilla():
    """ Carga la pantalla de Generación de Pagos """
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # Cargamos solo empleados activos para el dropdown
        cursor.execute("""
            SELECT id, nombres, apellidos, modalidad_pago 
            FROM empleados 
            WHERE activo = TRUE 
            ORDER BY nombres
        """)
        empleados = cursor.fetchall()
    
    return render_template('finanzas/planilla.html', empleados=empleados)

@finanzas_bp.route('/gestion-fondo', methods=['GET'])
@login_required
def ver_fondo_admin():
    """ Carga el Panel Administrativo del Fondo de Lealtad """
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # Asegurar que la tabla existe (Lazy Init)
        _ensure_fondo_table_exists(cursor)

        # Determine Current Month/Year for Projection
        from datetime import date
        today = date.today()
        cur_year = today.year
        cur_month = today.month

        # Obtenemos lista de empleados con sus saldos actuales Y DATOS PARA CALCULO
        cursor.execute("""
            SELECT id, nombres, apellidos, saldo_fondo_acumulado, 
                   meta_activacion_mensual, estado_fondo,
                   tipo_salario, sueldo_fijo_mensual, porcentaje_productos, porcentaje_fondo
            FROM empleados 
            WHERE activo = TRUE 
            ORDER BY saldo_fondo_acumulado DESC
        """)
        empleados_db = cursor.fetchall()
        
        empleados_procesados = []
        for emp in empleados_db:
             # Convertir a dict mutable
             e_dict = dict(emp)
             
             # 1. Obtener Porcentaje CORRECTO para este mes (Usando el helper existente)
             # Esto prioriza: Config Mensual Específica > Config Mensual Global > Config Sistema > Default
             pct_aplicar = _get_porcentaje_fondo(cursor, cur_year, cur_month, e_dict['id'])
             
             meta = float(e_dict['meta_activacion_mensual'] or 0)
             
             # Calcular Proyección Mes Actual
             progreso, base = _calcular_metricas_fondo(
                cursor, 
                e_dict['id'], 
                e_dict['tipo_salario'], 
                e_dict['sueldo_fijo_mensual'] or 0, 
                e_dict['porcentaje_productos'] or 0
             )
             
             proyeccion = base * (pct_aplicar / 100)
             
             # Agregamos datos calculados al objeto
             e_dict['proyeccion_actual'] = proyeccion
             e_dict['progreso_meta'] = progreso
             # Para debug visual si se requiere:
             e_dict['pct_usado'] = pct_aplicar 
             e_dict['cumple_meta'] = (progreso >= meta)
             
             empleados_procesados.append(e_dict)
        
        # Obtener el porcentaje GLOBAL actual para mostrar en el modal (Sincronía UI-Backend)
        pct_global_actual = _get_porcentaje_fondo(cursor, cur_year, cur_month, None)

    return render_template('finanzas/fondo_admin.html', empleados=empleados_procesados, pct_global_actual=pct_global_actual)

# --- AGREGAR ESTO EN routes_finanzas.py ---


# ==============================================================================
# 3. ENDPOINT: REGISTRAR INGRESOS (Y MONEDERO)
# ==============================================================================
@finanzas_bp.route('/ingresos/nuevo', methods=['GET', 'POST'])
@login_required
def registrar_ingreso():
    """
    Registra un Nuevo Ingreso Financiero.
    
    Tipos:
    - Abono a Monedero / Adelanto Cliente: Aumenta saldo cliente + Ingreso Caja.
    - Academia / Pago Gerencia / Prestamo: Ingreso Caja solamente.
    """
    
    if request.method == 'POST':
        tipo_ingreso = request.form.get('tipo_ingreso') # 'Abono Cliente', 'Academia', 'Prestamo', 'Gerencia', 'Otros'
        fecha = request.form.get('fecha')
        monto = float(request.form.get('monto'))
        metodo_pago = request.form.get('metodo_pago')
        cliente_id = request.form.get('cliente_id') # Solo si es Abono o vinculado
        descripcion = request.form.get('descripcion')
        abonar_monedero = 'abonar_monedero' in request.form # Checkbox
        
        sucursal_id = session.get('sucursal_id')
        if not sucursal_id:
            flash("Error: No se ha seleccionado una sucursal.", "danger")
            return redirect(url_for('finanzas.registrar_ingreso'))

        db = get_db()
        try:
            with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # 1. Obtener Caja Abierta
                cursor.execute("""
                    SELECT id FROM caja_sesiones 
                    WHERE usuario_id = %s AND sucursal_id = %s AND estado = 'Abierta'
                """, (current_user.id, sucursal_id))
                caja = cursor.fetchone()
                
                if not caja:
                    flash("Debe tener una CAJA ABIERTA para registrar ingresos.", "warning")
                    return redirect(url_for('finanzas.registrar_ingreso'))
                
                caja_id = caja['id']
                
                # 2. Registrar Movimiento en Caja
                concepto_final = f"{tipo_ingreso}: {descripcion}"
                
                # Insertar Movimiento
                cursor.execute("""
                    INSERT INTO movimientos_caja (caja_sesion_id, tipo, monto, concepto, metodo_pago, usuario_id, fecha)
                    VALUES (%s, 'INGRESO', %s, %s, %s, %s, %s)
                    RETURNING id
                """, (caja_id, monto, concepto_final, metodo_pago, current_user.id, fecha))
                
                mov_id = cursor.fetchone()['id']
                
                # 3. Lógica Específica: ABONO A MONEDERO
                if tipo_ingreso == 'Abono Cliente' or abonar_monedero:
                    if not cliente_id:
                        raise ValueError("Debe seleccionar un cliente para abonar al monedero.")
                    
                    try:
                        # Actualizar Saldo Cliente
                        cursor.execute("""
                            UPDATE clientes 
                            SET saldo_monedero = COALESCE(saldo_monedero, 0) + %s 
                            WHERE id = %s
                        """, (monto, cliente_id))
                        flash(f"Ingreso registrado y abonado S/ {monto:.2f} al monedero del cliente.", "success")
                    except Exception as e:
                        # Si falla (ej. no existe columna saldo_monedero por permisos), no crashear todo el ingreso
                        current_app.logger.error(f"No se pudo actualizar monedero: {e}")
                        flash(f"Ingreso registrado en CAJA, pero no se pudo actualizar el Monedero Virtual (Verifique permisos DB).", "warning")
                    
                    # Registrar Historial Puntos / Monedero (Opcional, si queremos trazarlo)
                    # Podemos usar la tabla 'puntos_historial' adaptada o crear 'monedero_historial'
                    # Por ahora, agregamos al concepto de caja que fue a monedero.
                    
                else:
                    flash(f"Ingreso de S/ {monto:.2f} registrado correctamente.", "success")
                
                db.commit()
                return redirect(url_for('finanzas.registrar_ingreso'))

        except Exception as e:
            flash(f"Error al registrar ingreso: {e}", "danger")
            return redirect(url_for('finanzas.registrar_ingreso'))

    # GET: Mostrar Formulario
    # Necesitamos lista de clientes para el select
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # CORREGIDO: Eliminamos 'WHERE activo = TRUE' porque la columna activo no existe en la tabla clientes
        cursor.execute("SELECT id, razon_social_nombres, apellidos, numero_documento FROM clientes ORDER BY razon_social_nombres")
        clientes = cursor.fetchall()
        
    return render_template('finanzas/form_ingreso.html', clientes=clientes, fecha_hoy=date.today())

@finanzas_bp.route('/fondo/penalidad', methods=['POST'])
@login_required
def aplicar_penalidad_fondo():
    # Validar permisos (Solo Admin)
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        flash("Acceso denegado.", "danger")
        return redirect(url_for('main.index'))

    empleado_id = request.form.get('empleado_id')
    motivo = request.form.get('motivo')
    
    # Validar monto
    try:
        monto = float(request.form.get('monto'))
    except (ValueError, TypeError):
        flash("El monto ingresado no es válido.", "danger")
        return redirect(url_for('finanzas.ver_fondo_admin'))

    db = get_db()
    try:
        with db.cursor() as cursor:
            # 1. Obtener saldo actual
            cursor.execute("SELECT saldo_fondo_acumulado FROM empleados WHERE id = %s", (empleado_id,))
            res = cursor.fetchone()
            
            if not res:
                flash("Empleado no encontrado", "danger")
                return redirect(url_for('finanzas.ver_fondo_admin'))
                
            saldo_actual = float(res[0] or 0)
            nuevo_saldo = saldo_actual - monto
            
            # 2. Permitir saldos negativos (Deuda)
            # if nuevo_saldo < 0:
            #    ... (Logic removed to allow negative balance)

            if monto > 0:
                # 3. Actualizar Empleado
                cursor.execute("UPDATE empleados SET saldo_fondo_acumulado = %s WHERE id = %s", (nuevo_saldo, empleado_id))
                
                # 4. Registrar en Historial
                # Usamos current_user.id para saber quién puso la multa.
                # Asegúrate que tu tabla movimientos_fondo tenga la columna creado_por_usuario_id 
                # Si no la tiene, quita esa columna del INSERT.
                cursor.execute("""
                    INSERT INTO movimientos_fondo (empleado_id, tipo_movimiento, monto, motivo, creado_por_usuario_id)
                    VALUES (%s, 'Penalidad', %s, %s, %s)
                """, (empleado_id, monto, motivo, current_user.id))

                db.commit()
                flash("🔴 Infracción registrada y descuento aplicado.", "success")
            else:
                flash("No se aplicó descuento (Monto 0).", "info")

    except Exception as e:
        db.rollback()
        flash(f"Error al aplicar penalidad: {e}", "danger")

    return redirect(url_for('finanzas.ver_fondo_admin'))


# --- AGREGAR AL FINAL DE routes_finanzas.py ---

@finanzas_bp.route('/fondo/actualizar-meta', methods=['POST'])
@login_required
def actualizar_meta_fondo():
    # 1. Seguridad: Solo Admin
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        flash("Acceso denegado.", "danger")
        return redirect(url_for('main.index'))

    # 2. Recibir Datos
    empleado_id = request.form.get('empleado_id')
    nueva_meta = request.form.get('nueva_meta')

    try:
        monto = float(nueva_meta)
        if monto < 0:
            flash("La meta no puede ser negativa.", "warning")
            return redirect(url_for('finanzas.ver_fondo_admin'))
    except (ValueError, TypeError):
        flash("Monto inválido.", "danger")
        return redirect(url_for('finanzas.ver_fondo_admin'))

    # 3. Guardar en Base de Datos
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                UPDATE empleados 
                SET meta_activacion_mensual = %s 
                WHERE id = %s
            """, (monto, empleado_id))
            db.commit()
            flash(f"✅ Meta actualizada a S/ {monto:.2f}", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error al actualizar: {e}", "danger")

    return redirect(url_for('finanzas.ver_fondo_admin'))


@finanzas_bp.route('/api/confirmar-pago-planilla', methods=['POST'])
@login_required
def confirmar_pago_planilla():
    data = request.json
    empleado_id = data.get('empleado_id')
    f_inicio = data.get('fecha_inicio')
    f_fin = data.get('fecha_fin')
    monto_total = data.get('monto_total')

    if not empleado_id or not f_inicio or not f_fin:
        return jsonify({'error': 'Datos incompletos'}), 400

    db = get_db()
    try:
        # Usamos RealDictCursor explícitamente para evitar errores de índice
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            
            # 1. Crear el registro "Padre" de la Planilla
            cursor.execute("""
                INSERT INTO planillas (empleado_id, fecha_inicio_periodo, fecha_fin_periodo, total_pagado)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (empleado_id, f_inicio, f_fin, monto_total))
            
            # Capturamos el ID de la nueva planilla
            nueva_planilla = cursor.fetchone()
            planilla_id = nueva_planilla['id']

            # 2. MARCAR VENTAS COMO PAGADAS (Bloquearlas)
            cursor.execute("""
                UPDATE ventas 
                SET pago_nomina_id = %s 
                WHERE empleado_id = %s 
                  AND fecha_venta BETWEEN %s AND %s
                  AND estado != 'Anulada'
                  AND pago_nomina_id IS NULL
            """, (planilla_id, empleado_id, f_inicio, f_fin))

            # 3. MARCAR ADELANTOS COMO DEDUCIDOS (Bloquearlos)
            cursor.execute("""
                UPDATE gastos
                SET deducido_en_planilla_id = %s
                WHERE empleado_beneficiario_id = %s
                  AND fecha BETWEEN %s AND %s
                  AND deducido_en_planilla_id IS NULL
            """, (planilla_id, empleado_id, f_inicio, f_fin))

            # 4. MARCAR PENALIDADES COMO DEDUCIDAS (Bloquearlas)
            cursor.execute("""
                UPDATE empleado_penalidades
                SET deducido_en_planilla_id = %s
                WHERE empleado_id = %s
                  AND fecha_registro::date BETWEEN %s AND %s
                  AND deducido_en_planilla_id IS NULL
            """, (planilla_id, empleado_id, f_inicio, f_fin))

            # 5. APLICAR AMORTIZACIÓN A DEUDAS
            # Recibiremos la lista de amortizaciones desde el Frontend
            deudas_amortizadas = data.get('deudas_amortizadas', [])
            for deuda in deudas_amortizadas:
                d_id = deuda.get('id')
                m_deducido = float(deuda.get('monto_deducido', 0))
                if m_deducido > 0:
                    cursor.execute("""
                        UPDATE empleado_deudas
                        SET monto_pagado = monto_pagado + %s,
                            estado = CASE 
                                        WHEN (monto_total - (monto_pagado + %s)) <= 0.01 THEN 'Pagado' 
                                        ELSE 'Pendiente' 
                                     END
                        WHERE id = %s
                    """, (m_deducido, m_deducido, d_id))

            db.commit()
            return jsonify({'mensaje': 'Pago registrado correctamente. Ventas cerradas.', 'planilla_id': planilla_id})

    except Exception as e:
        if db: db.rollback()
        # Imprimir el error en la consola de Railway para verlo
        print(f"Error confirmando pago: {e}")
        return jsonify({'error': str(e)}), 500
    
# --- GESTIÓN DE PROPINAS ---

@finanzas_bp.route('/propinas/registrar', methods=['POST'])
@login_required
def registrar_propina():
    """
    Registra que un cliente dejó propina. 
    Esto suma al saldo de caja (si es Efectivo) o saldo digital.
    """
    empleado_id = request.form.get('empleado_id')
    monto = float(request.form.get('monto'))
    metodo = request.form.get('metodo_pago') # Efectivo, Yape, etc.
    venta_id = request.form.get('venta_id') # Opcional

    db = get_db()
    try:
        with db.cursor() as cursor:
            # 1. Guardar la propina
            cursor.execute("""
                INSERT INTO propinas (empleado_id, monto, metodo_pago, registrado_por, entregado_al_barbero)
                VALUES (%s, %s, %s, %s, FALSE)
            """, (empleado_id, monto, metodo, current_user.id))
            
            # 2. Registrar MOVIMIENTO DE CAJA (INGRESO)
            # Para que cuadre tu caja del día
            cursor.execute("""
                INSERT INTO movimientos_caja (tipo, monto, concepto, metodo_pago, usuario_id)
                VALUES ('INGRESO', %s, 'Propina Cliente - Custodia', %s, %s)
            """, (monto, metodo, current_user.id))
            
            db.commit()
            flash(f"✅ Propina de S/ {monto:.2f} registrada en caja.", "success")
            
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")

    return redirect(request.referrer) # Vuelve a la página donde estabas

# En app/routes_finanzas.py

# En app/routes_finanzas.py

@finanzas_bp.route('/propinas/pagar', methods=['POST'])
@login_required
def pagar_propina_a_barbero():
    propina_id = request.form.get('propina_id')
    sucursal_id = session.get('sucursal_id')
    
    if not sucursal_id:
        return jsonify({'error': 'Error de sesión: No se detectó la sucursal.'}), 400

    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Obtener datos de la propina
            cursor.execute("""
                SELECT p.monto, p.empleado_id, p.metodo_pago, e.nombres 
                FROM propinas p
                JOIN empleados e ON p.empleado_id = e.id
                WHERE p.id = %s
            """, (propina_id,))
            data = cursor.fetchone()
            
            if not data:
                return jsonify({'error': 'Propina no encontrada'}), 404
                
            monto = float(data['monto'])
            nombre_barbero = data['nombres']

            # 2. Buscar la CAJA ABIERTA
            cursor.execute("""
                SELECT id FROM caja_sesiones 
                WHERE usuario_id = %s AND estado = 'Abierta'
            """, (current_user.id,))
            sesion = cursor.fetchone()
            
            if not sesion:
                return jsonify({'error': 'No tienes una caja abierta para registrar esta salida.'}), 400
            
            caja_id = sesion['id']

            # 4. Marcar propina como ENTREGADA
            cursor.execute("""
                UPDATE propinas 
                SET entregado_al_barbero = TRUE, fecha_entrega = CURRENT_TIMESTAMP 
                WHERE id = %s
            """, (propina_id,))
            
            # --- NOTA: YA NO REGISTRAMOS GASTO ---
            # El dashboard calcula "Ingresos Efectivo" sumando ventas + propinas NO entregadas.
            # Al marcarla como entregada, automáticamente "desaparece" del Ingreso Calculado y del Total en Caja.
            # Si registráramos un Gasto, se descontaría DOBLE (una vez por salir del Ingreso, otra por el Gasto).
            # Por solicitud del usuario: "No sumarse a los egresos".
            
            db.commit()
            return jsonify({'mensaje': 'Propina entregada correctamente.'})

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


# ==============================================================================
# 5. ENDPOINTS: PENALIDADES Y DEUDAS
# ==============================================================================

@finanzas_bp.route('/api/empleado/<int:empleado_id>/deuda/nueva', methods=['POST'])
@login_required
def nueva_deuda_empleado(empleado_id):
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        return jsonify({'error': 'Acceso denegado'}), 403
        
    data = request.json
    concepto = data.get('concepto')
    monto_total = data.get('monto_total')
    
    if not concepto or not monto_total:
        return jsonify({'error': 'Concepto y monto son requeridos'}), 400
        
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO empleado_deudas (empleado_id, concepto, monto_total)
                VALUES (%s, %s, %s)
            """, (empleado_id, concepto, float(monto_total)))
            db.commit()
            return jsonify({'mensaje': 'Deuda registrada correctamente'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500

@finanzas_bp.route('/api/empleado/<int:empleado_id>/penalidad/nueva', methods=['POST'])
@login_required
def nueva_penalidad_empleado(empleado_id):
    if getattr(current_user, 'rol_nombre', '') != 'Administrador':
        return jsonify({'error': 'Acceso denegado'}), 403
        
    data = request.json
    motivo = data.get('motivo')
    monto = data.get('monto')
    
    if not motivo or not monto:
        return jsonify({'error': 'Motivo y monto son requeridos'}), 400
        
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO empleado_penalidades (empleado_id, motivo, monto)
                VALUES (%s, %s, %s)
            """, (empleado_id, motivo, float(monto)))
            db.commit()
            return jsonify({'mensaje': 'Penalidad registrada correctamente'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
