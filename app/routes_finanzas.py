from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
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


def proceso_cierre_mensual_fondo():
    
    # Esto corre automáticamente a fin de mes.
    # Verifica quién cumplió la meta y consolida el dinero en su 'bolsa'.
    
    db = get_db()
    # Rango del mes que cerramos (Ej: estamos 1ro dic, cerramos nov)
    # ... lógica de fechas ...
    
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT id, meta_activacion_mensual, porcentaje_fondo, tipo_salario FROM empleados WHERE activo=TRUE")
        empleados = cursor.fetchall()

        for emp in empleados:
            produccion = _calcular_produccion_mes_actual(cursor, emp['id'], emp['tipo_salario'])
            
            # REGLA C: Cierre de Mes
            if produccion >= float(emp['meta_activacion_mensual']):
                aporte = produccion * (float(emp['porcentaje_fondo']) / 100)
                
                # Sumar al acumulado
                cursor.execute("""
                    UPDATE empleados 
                    SET saldo_fondo_acumulado = saldo_fondo_acumulado + %s 
                    WHERE id = %s
                """, (aporte, emp['id']))

                # Registrar Historial
                cursor.execute("""
                    INSERT INTO movimientos_fondo (empleado_id, tipo_movimiento, monto, motivo)
                    VALUES (%s, 'Aporte_Mensual', %s, 'Meta Cumplida - Cierre Mes')
                """, (emp['id'], aporte))
            else:
                # No llegó a la meta - Registro Neutro
                cursor.execute("""
                    INSERT INTO movimientos_fondo (empleado_id, tipo_movimiento, monto, motivo)
                    VALUES (%s, 'Intento_Fallido', 0, 'No alcanzó meta mensual')
                """, (emp['id'],))
        
        db.commit()
        print("✅ Cierre de Fondo de Lealtad completado.")




# ==============================================================================
# 1. FUNCIÓN AUXILIAR: LÓGICA DE TRAMOS (CEREBRO MATEMÁTICO)
# ==============================================================================
def _calcular_desglose_tramos(cursor, venta_actual, acumulado_previo):
    # Toma un monto de venta y lo distribuye en los niveles disponibles (Base, Master, Top)
    # basándose en cuánto ya tenía acumulado el empleado en el mes.
    
    cursor.execute("SELECT * FROM esquema_comisiones ORDER BY monto_minimo ASC")
    tramos = cursor.fetchall()
    
    desglose = []
    monto_restante = float(venta_actual)
    cursor_acumulado = float(acumulado_previo) # Punto de partida en la "barra de experiencia"
    
    comision_total = 0.0
    
    for tramo in tramos:
        if monto_restante <= 0:
            break
            
        # Definir techos y pisos del nivel actual
        techo_tramo = float(tramo['monto_maximo']) if tramo['monto_maximo'] else float('inf')
        piso_tramo = float(tramo['monto_minimo'])
        tasa = float(tramo['porcentaje'])
        
        # 1. ¿Este tramo ya fue llenado completamente en días anteriores?
        if cursor_acumulado >= techo_tramo:
            continue 
            
        # 2. ¿Cuánto espacio libre queda en este tramo?
        # Ej: Si el techo es 4500 y voy en 4200, quedan 300 libres.
        espacio_disponible = techo_tramo - max(piso_tramo, cursor_acumulado)
        
        # 3. ¿Cuánto de mi venta actual cabe aquí?
        monto_a_computar = min(monto_restante, espacio_disponible)
        
        if monto_a_computar > 0:
            subtotal_comision = monto_a_computar * (tasa / 100)
            desglose.append({
                'nivel': tramo['nombre_nivel'],
                'tasa': tasa,
                'venta_base': monto_a_computar,
                'comision': subtotal_comision
            })
            
            comision_total += subtotal_comision
            monto_restante -= monto_a_computar
            cursor_acumulado += monto_a_computar # Mover el cursor para la siguiente iteración
            
    return desglose, comision_total


# ==============================================================================
# 2. ENDPOINT PRINCIPAL: CALCULAR PLANILLA
# ==============================================================================
@finanzas_bp.route('/api/calcular-planilla-empleado', methods=['POST'])
@login_required
def calcular_planilla_preliminar():
    # Calcula el pago exacto considerando cruces de mes, tramos marginales y adelantos.
    
    data = request.json
    empleado_id = data.get('empleado_id')
    f_inicio_str = data.get('fecha_inicio')
    f_fin_str = data.get('fecha_fin')

    db = get_db()
    
    try:
        # Convertir strings a objetos Date
        f_inicio = datetime.strptime(f_inicio_str, '%Y-%m-%d').date()
        f_fin = datetime.strptime(f_fin_str, '%Y-%m-%d').date()
        
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # A. Obtener Datos Básicos
            cursor.execute("SELECT * FROM empleados WHERE id = %s", (empleado_id,))
            empleado = cursor.fetchone()
            
            if not empleado:
                return jsonify({'error': 'Empleado no encontrado'}), 404
            
            cursor.execute("SELECT sueldo_minimo_vital FROM configuracion_sistema LIMIT 1")
            config = cursor.fetchone()
            smv = float(config['sueldo_minimo_vital']) if config else 1130.00
            
            # Variables acumuladoras para la respuesta final
            total_comisiones_periodo = 0.00
            detalle_final = []
            mensajes_alerta = []
            reintegro_smv_total = 0.00
            
            # B. Detectar Sub-Periodos (Por si la semana cruza dos meses)
            sub_periodos = []
            
            if f_inicio.month == f_fin.month and f_inicio.year == f_fin.year:
                # Caso Normal: Todo en el mismo mes
                sub_periodos.append({'inicio': f_inicio, 'fin': f_fin})
            else:
                # Caso Cruzado: Partir la semana
                ultimo_dia_mes_1 = date(f_inicio.year, f_inicio.month, monthrange(f_inicio.year, f_inicio.month)[1])
                primer_dia_mes_2 = f_fin.replace(day=1)
                
                sub_periodos.append({'inicio': f_inicio, 'fin': ultimo_dia_mes_1})
                sub_periodos.append({'inicio': primer_dia_mes_2, 'fin': f_fin})
            
            # C. Procesar cada Sub-Periodo
            for periodo in sub_periodos:
                p_ini = periodo['inicio']
                p_fin = periodo['fin']
                
                # 1. Calcular Venta del Sub-Periodo (Lo que se va a pagar ahora)
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s AND v.fecha_venta BETWEEN %s AND %s 
                    AND v.estado != 'Anulada'
                """, (empleado_id, p_ini, p_fin))
                venta_actual = float(cursor.fetchone()['total'])
                
                # 2. Calcular Acumulado Previo en ese Mes (Para saber en qué nivel de la tabla cae)
                inicio_de_ese_mes = p_ini.replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s AND v.fecha_venta >= %s AND v.fecha_venta < %s
                    AND v.estado != 'Anulada'
                """, (empleado_id, inicio_de_ese_mes, p_ini))
                acumulado_previo = float(cursor.fetchone()['total'])
                
                # 3. Calcular Comisiones usando la función auxiliar
                desglose_tramos, comision_sub = _calcular_desglose_tramos(cursor, venta_actual, acumulado_previo)
                
                total_comisiones_periodo += comision_sub
                
                # Guardar detalle visual para la boleta
                detalle_final.append({
                    'fechas': f"{p_ini.strftime('%d/%m')} al {p_fin.strftime('%d/%m')}",
                    'venta': venta_actual,
                    'acumulado_antes': acumulado_previo,
                    'desglose': desglose_tramos
                })

                # 4. Cálculo de Reintegro SMV (Solo si es fin de mes)
                # Verifica si el sub-periodo termina el último día del mes
                ultimo_dia_del_mes_actual = date(p_ini.year, p_ini.month, monthrange(p_ini.year, p_ini.month)[1])
                
                if p_fin == ultimo_dia_del_mes_actual:
                    # Simulamos cuánto ganó en todo el mes para ver si llegó al mínimo
                    total_mes_acumulado = acumulado_previo + venta_actual
                    _, comision_teorica_mes_completo = _calcular_desglose_tramos(cursor, total_mes_acumulado, 0)
                    
                    if comision_teorica_mes_completo < smv:
                        diferencia = smv - comision_teorica_mes_completo
                        reintegro_smv_total += diferencia
                        mensajes_alerta.append(f"⚠️ Reintegro Ley (Cierre {p_ini.strftime('%B')}): S/ {diferencia:.2f}")

            # D. DEDUCCIÓN DE ADELANTOS (GASTOS)
            cursor.execute("""
                SELECT COALESCE(SUM(monto), 0) as total_adelantos
                FROM gastos 
                WHERE empleado_beneficiario_id = %s 
                  AND fecha BETWEEN %s AND %s
            """, (empleado_id, f_inicio, f_fin))
            
            row_adelantos = cursor.fetchone()
            total_adelantos = float(row_adelantos['total_adelantos']) if row_adelantos else 0.00
            
            # E. CÁLCULO FINAL
            total_bruto = total_comisiones_periodo + reintegro_smv_total
            total_neto_pagar = total_bruto - total_adelantos

            # --- RESPUESTA JSON PARA EL FRONTEND ---
            return jsonify({
                'empleado': f"{empleado['nombres']} {empleado['apellidos']}",
                'total_a_pagar': total_neto_pagar,
                'resumen_financiero': {
                    'bruto_comisiones': total_comisiones_periodo,
                    'reintegro_smv': reintegro_smv_total,
                    'descuento_adelantos': total_adelantos,
                    'neto_a_pagar': total_neto_pagar
                },
                'detalle_calculo': detalle_final,
                'mensajes': mensajes_alerta
            })

    except Exception as e:
        # Imprimir error en logs para depuración
        print(f"Error en calcular_planilla: {e}") 
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
        # Obtenemos lista de empleados con sus saldos actuales
        cursor.execute("""
            SELECT id, nombres, apellidos, saldo_fondo_acumulado, 
                   meta_activacion_mensual, estado_fondo
            FROM empleados 
            WHERE activo = TRUE 
            ORDER BY saldo_fondo_acumulado DESC
        """)
        empleados = cursor.fetchall()
        
    return render_template('finanzas/fondo_admin.html', empleados=empleados)

# --- AGREGAR ESTO EN routes_finanzas.py ---

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
            
            # 2. Evitar saldos negativos (Opcional, según tu regla de negocio)
            if nuevo_saldo < 0:
                # Si quieres permitir deuda, borra este if. 
                # Si quieres dejarlo en 0:
                monto = saldo_actual 
                nuevo_saldo = 0
                flash(f"El saldo era insuficiente. Se descontó el máximo posible (S/ {monto:.2f}).", "warning")

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



