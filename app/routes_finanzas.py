from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user  
import psycopg2
import psycopg2.extras
from datetime import date
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

@finanzas_bp.route('/api/fondo-lealtad', methods=['GET'])
@login_required
def dashboard_fondo_lealtad():
    """
    API para la App Móvil y Dashboard Web: Devuelve JSON con el progreso del fondo.
    """
    # Verificamos si el usuario logueado está asociado a un empleado
    # OJO: Asegúrate que tu modelo de User tenga este campo, si no, hay que buscarlo
    empleado_id = getattr(current_user, 'empleado_id', None)
    
    # Si usas un sistema donde el ID de usuario es igual al de empleado o tienes una tabla de relación:
    if not empleado_id:
        # Fallback: intentar buscar empleado por el email del usuario actual
        db = get_db()
        with db.cursor() as cursor:
            cursor.execute("SELECT id FROM empleados WHERE email = %s", (current_user.email,)) # O el campo que uses para linkear
            res = cursor.fetchone()
            if res:
                empleado_id = res[0]
            else:
                return jsonify({'error': 'Usuario no vinculado a un empleado'}), 400

    db = get_db()
    data_response = {}

    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Configuración del Empleado
            cursor.execute("""
                SELECT meta_activacion_mensual, porcentaje_fondo, saldo_fondo_acumulado, 
                       tipo_salario, nombres, apellidos
                FROM empleados WHERE id = %s
            """, (empleado_id,))
            emp = cursor.fetchone()

            if not emp:
                 return jsonify({'error': 'Empleado no encontrado'}), 404

            meta = float(emp['meta_activacion_mensual'] or 0)
            porcentaje = float(emp['porcentaje_fondo'] or 0) / 100
            saldo_historico = float(emp['saldo_fondo_acumulado'] or 0)
            
            # 2. Calcular Producción
            produccion_actual = _calcular_produccion_mes_actual(cursor, empleado_id, emp['tipo_salario'])
            
            # 3. Proyección
            aporte_proyectado = produccion_actual * porcentaje
            progreso_porcentaje = min(100, (produccion_actual / meta) * 100) if meta > 0 else 100

            # 4. Gamificación
            estado_visual = {}
            if produccion_actual >= meta:
                estado_visual = {
                    'color': '#28a745', 'icono': '🎉', 'titulo': '¡BONO ACTIVADO!',
                    'mensaje': f'Asegurado: S/ {aporte_proyectado:.2f}', 'clase_css': 'bg-success'
                }
            elif produccion_actual >= (meta * 0.7):
                faltante = meta - produccion_actual
                estado_visual = {
                    'color': '#ffc107', 'icono': '🔥', 'titulo': '¡Estás muy cerca!',
                    'mensaje': f'Faltan S/ {faltante:.2f}', 'clase_css': 'bg-warning'
                }
            else:
                faltante = meta - produccion_actual
                estado_visual = {
                    'color': '#dc3545', 'icono': '💪', 'titulo': 'Tú puedes hacerlo',
                    'mensaje': f'Faltan S/ {faltante:.2f} para activar.', 'clase_css': 'bg-danger'
                }

            # 5. Historial
            cursor.execute("""
                SELECT fecha, tipo_movimiento, monto, motivo 
                FROM movimientos_fondo 
                WHERE empleado_id = %s 
                ORDER BY fecha DESC LIMIT 10
            """, (empleado_id,))
            historial = cursor.fetchall()
            
            data_response = {
                'resumen': {
                    'saldo_total_acumulado': saldo_historico,
                    'aporte_mes_proyectado': aporte_proyectado if produccion_actual >= meta else 0,
                    'meta_objetivo': meta,
                    'produccion_actual': produccion_actual
                },
                'gamificacion': {
                    'progreso_porcentaje': progreso_porcentaje,
                    **estado_visual
                },
                'historial': [dict(h) for h in historial]
            }

    except Exception as e:
        print(f"Error dashboard fondo: {e}")
        return jsonify({'error': str(e)}), 500

    return jsonify(data_response)

@finanzas_bp.route('/fondo/penalidad', methods=['POST'])
@login_required
def aplicar_penalidad_fondo():
    # Validar permisos de admin (ajusta según tu lógica de roles)
    # if not current_user.es_admin: ...
    
    empleado_id = request.form.get('empleado_id')
    motivo = request.form.get('motivo')
    monto = float(request.form.get('monto'))

    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT saldo_fondo_acumulado FROM empleados WHERE id = %s", (empleado_id,))
            res = cursor.fetchone()
            if not res:
                flash("Empleado no encontrado", "danger")
                return redirect(url_for('main.index'))
                
            saldo_actual = float(res[0] or 0)
            nuevo_saldo = saldo_actual - monto
            
            if nuevo_saldo < 0:
                monto = saldo_actual # Ajustar al máximo posible
                nuevo_saldo = 0
                flash(f"Saldo insuficiente. Se descontó el total disponible (S/ {monto:.2f}).", "warning")

            if monto > 0:
                cursor.execute("UPDATE empleados SET saldo_fondo_acumulado = %s WHERE id = %s", (nuevo_saldo, empleado_id))
                
                # Asumiendo que current_user tiene un atributo id o empleado_id válido para 'creado_por'
                # Si 'creado_por_usuario_id' es FK a empleados, usa el ID de empleado del admin.
                # Si es FK a usuarios, usa current_user.id
                
                # Para evitar errores con la FK corregida, asegúrate de enviar un ID válido de empleado
                admin_empleado_id = getattr(current_user, 'empleado_id', None) 
                # Si no tienes esto mapeado aún, pon 1 (suponiendo que 1 es el Admin principal) temporalmente o ajusta tu modelo User
                if not admin_empleado_id: admin_empleado_id = 1 

                cursor.execute("""
                    INSERT INTO movimientos_fondo (empleado_id, tipo_movimiento, monto, motivo, creado_por_usuario_id)
                    VALUES (%s, 'Penalidad', %s, %s, %s)
                """, (empleado_id, monto, motivo, admin_empleado_id))

                db.commit()
                flash("🔴 Penalidad aplicada.", "success")
            else:
                flash("No hay saldo para descontar.", "info")

    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")

    # Redirigir al perfil o lista de empleados (ajusta la ruta de retorno)
    return redirect(request.referrer or url_for('main.index'))


def proceso_cierre_mensual_fondo():
    """
    Esto corre automáticamente a fin de mes.
    Verifica quién cumplió la meta y consolida el dinero en su 'bolsa'.
    """
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

# --- Agregar al inicio de routes_finanzas.py ---
from datetime import datetime, timedelta

# ... (tus imports anteriores) ...

from datetime import datetime, timedelta, date
from calendar import monthrange

def _calcular_desglose_tramos(cursor, venta_actual, acumulado_previo):
    """
    Función auxiliar: Toma un monto de venta y lo "pica" en pedacitos 
    según los espacios disponibles en cada nivel (50%, 55%, 60%).
    """
    cursor.execute("SELECT * FROM esquema_comisiones ORDER BY monto_minimo ASC")
    tramos = cursor.fetchall()
    
    desglose = []
    monto_restante = float(venta_actual)
    cursor_acumulado = float(acumulado_previo) # Dónde empieza mi "barra de experiencia"
    
    comision_total = 0.0
    
    for tramo in tramos:
        if monto_restante <= 0:
            break
            
        techo_tramo = float(tramo['monto_maximo']) if tramo['monto_maximo'] else float('inf')
        piso_tramo = float(tramo['monto_minimo'])
        tasa = float(tramo['porcentaje'])
        
        # 1. ¿Este tramo ya lo pasé antes de empezar esta venta?
        if cursor_acumulado >= techo_tramo:
            continue # Ya llené este saco, paso al siguiente
            
        # 2. ¿Cuánto espacio libre queda en este tramo?
        # Si mi acumulado está en 4200 y el techo es 4500, tengo 300 de espacio.
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
            cursor_acumulado += monto_a_computar # Avanzo mi cursor
            
    return desglose, comision_total

@finanzas_bp.route('/api/calcular-planilla-empleado', methods=['POST'])
@login_required
def calcular_planilla_preliminar():
    data = request.json
    empleado_id = data.get('empleado_id')
    f_inicio_str = data.get('fecha_inicio')
    f_fin_str = data.get('fecha_fin')

    db = get_db()
    
    try:
        # Convertir a objetos Date
        f_inicio = datetime.strptime(f_inicio_str, '%Y-%m-%d').date()
        f_fin = datetime.strptime(f_fin_str, '%Y-%m-%d').date()
        
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Datos Empleado
            cursor.execute("SELECT * FROM empleados WHERE id = %s", (empleado_id,))
            empleado = cursor.fetchone()
            
            # Configuracion SMV
            cursor.execute("SELECT sueldo_minimo_vital FROM configuracion_sistema LIMIT 1")
            config = cursor.fetchone()
            smv = float(config['sueldo_minimo_vital']) if config else 1130.00
            
            total_periodo_pagar = 0.00
            detalle_final = []
            mensajes_alerta = []
            
            # --- DETECCIÓN DE CRUCE DE MES (Ej: Semana 5: 29 Dic - 03 Ene) ---
            sub_periodos = []
            
            if f_inicio.month == f_fin.month:
                # Caso Normal: Todo cae en el mismo mes
                sub_periodos.append({'inicio': f_inicio, 'fin': f_fin, 'mes': f_inicio.month})
            else:
                # Caso Cruzado: Hay que partir la semana en dos
                # Periodo A: Inicio -> Fin de Mes 1
                ultimo_dia_mes_1 = date(f_inicio.year, f_inicio.month, monthrange(f_inicio.year, f_inicio.month)[1])
                sub_periodos.append({'inicio': f_inicio, 'fin': ultimo_dia_mes_1, 'mes': f_inicio.month})
                
                # Periodo B: 1ro de Mes 2 -> Fin
                primer_dia_mes_2 = f_fin.replace(day=1)
                sub_periodos.append({'inicio': primer_dia_mes_2, 'fin': f_fin, 'mes': f_fin.month})
            
            # --- PROCESAR CADA SUB-PERIODO ---
            reintegro_smv_total = 0.00
            
            for periodo in sub_periodos:
                p_ini = periodo['inicio']
                p_fin = periodo['fin']
                
                # 1. Calcular Venta del Sub-Periodo
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s AND v.fecha_venta BETWEEN %s AND %s 
                    AND v.estado != 'Anulada'
                """, (empleado_id, p_ini, p_fin))
                venta_actual = float(cursor.fetchone()['total'])
                
                # 2. Calcular Acumulado Previo en ese Mes (Desde el día 1 hasta ayer)
                inicio_de_ese_mes = p_ini.replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(vi.subtotal_item_neto), 0) as total
                    FROM venta_items vi JOIN ventas v ON vi.venta_id = v.id
                    WHERE v.empleado_id = %s AND v.fecha_venta >= %s AND v.fecha_venta < %s
                    AND v.estado != 'Anulada'
                """, (empleado_id, inicio_de_ese_mes, p_ini))
                acumulado_previo = float(cursor.fetchone()['total'])
                
                # 3. Calcular Comisiones Escalonadas (La magia de los tramos)
                desglose_tramos, comision_sub = _calcular_desglose_tramos(cursor, venta_actual, acumulado_previo)
                
                total_periodo_pagar += comision_sub
                
                # Guardar detalle para el recibo
                detalle_final.append({
                    'fechas': f"{p_ini.strftime('%d/%m')} al {p_fin.strftime('%d/%m')}",
                    'venta': venta_actual,
                    'acumulado_antes': acumulado_previo,
                    'acumulado_despues': acumulado_previo + venta_actual,
                    'desglose': desglose_tramos
                })

                # --- 4. CÁLCULO DE REINTEGRO SMV (Solo si es fin de mes) ---
                # Si este sub-periodo toca el último día del mes, verificamos el SMV del mes completo
                ultimo_dia_del_mes_actual = date(p_ini.year, p_ini.month, monthrange(p_ini.year, p_ini.month)[1])
                
                if p_fin == ultimo_dia_del_mes_actual:
                    # Traemos toda la comisión ganada en el mes
                    total_mes_acumulado = acumulado_previo + venta_actual
                    
                    # Simulamos comisión total del mes (aproximada para validar SMV)
                    # Nota: Para ser exactos habría que guardar el histórico de pagos, 
                    # aquí recalculamos cuánto DEBIÓ ganar en el mes entero.
                    _, comision_total_mes_teorica = _calcular_desglose_tramos(cursor, total_mes_acumulado, 0)
                    
                    if comision_total_mes_teorica < smv:
                        reintegro = smv - comision_total_mes_teorica
                        reintegro_smv_total += reintegro
                        mensajes_alerta.append(f"⚠️ Reintegro Ley Mes {p_ini.strftime('%B')}: S/ {reintegro:.2f}")

            # --- RESPUESTA FINAL JSON ---
            return jsonify({
                'empleado': f"{empleado['nombres']} {empleado['apellidos']}",
                'total_a_pagar': total_periodo_pagar + reintegro_smv_total,
                'reintegro_smv': reintegro_smv_total,
                'detalle_calculo': detalle_final,
                'mensajes': mensajes_alerta
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    
    
@finanzas_bp.route('/api/guardar-planilla', methods=['POST'])
@login_required
def guardar_planilla():
    # Aquí recibirías el JSON final confirmado por el admin y harías el INSERT en la tabla 'planillas'
    # ... Lógica de INSERT ...
    return jsonify({'mensaje': 'Planilla guardada correctamente'})


