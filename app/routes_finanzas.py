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


