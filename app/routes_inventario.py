from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
from .db import get_db

inventario_bp = Blueprint('inventario', __name__, url_prefix='/inventario')

# --- FUNCIÓN AUXILIAR: REGISTRAR EN KARDEX ---
def registrar_movimiento_kardex(cursor, producto_id, tipo, cantidad, motivo, usuario_id, venta_id=None):
    # 1. Obtener stock actual
    cursor.execute("SELECT stock_actual FROM productos WHERE id = %s", (producto_id,))
    res = cursor.fetchone()
    if not res: return
    stock_ant = res['stock_actual'] if isinstance(res, dict) else res[0]
    
    # 2. Calcular nuevo stock
    stock_nuevo = stock_ant + cantidad
    
    # 3. Actualizar Producto
    cursor.execute("UPDATE productos SET stock_actual = %s WHERE id = %s", (stock_nuevo, producto_id))
    
    # 4. Insertar en Kardex
    cursor.execute("""
        INSERT INTO kardex (producto_id, tipo_movimiento, cantidad, stock_anterior, stock_actual, motivo, usuario_id, venta_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (producto_id, tipo, cantidad, stock_ant, stock_nuevo, motivo, usuario_id, venta_id))


@inventario_bp.route('/lista')
@login_required
def lista_inventario():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # Traemos productos con cálculo de estado
        cursor.execute("""
            SELECT id, nombre, precio_venta, stock_actual, stock_minimo,
                   CASE 
                       WHEN stock_actual <= 0 THEN 'Agotado'
                       WHEN stock_actual <= stock_minimo THEN 'Bajo'
                       ELSE 'Optimo'
                   END as estado_stock
            FROM productos 
            WHERE activo = TRUE 
            ORDER BY stock_actual ASC
        """)
        productos = cursor.fetchall()
    return render_template('inventario/lista.html', productos=productos)


@inventario_bp.route('/movimiento', methods=['POST'])
@login_required
def guardar_movimiento():
    producto_id = request.form.get('producto_id')
    tipo = request.form.get('tipo_movimiento') # 'COMPRA' o 'CONSUMO_INTERNO'
    
    try:
        cantidad_input = int(request.form.get('cantidad'))
    except (ValueError, TypeError):
        flash("Cantidad inválida", "danger")
        return redirect(url_for('inventario.lista_inventario'))

    nota = request.form.get('nota')
    
    if cantidad_input <= 0:
        flash("La cantidad debe ser mayor a 0", "warning")
        return redirect(url_for('inventario.lista_inventario'))

    # Definir signo (Positivo o Negativo)
    cantidad_final = cantidad_input
    if tipo == 'CONSUMO_INTERNO' or tipo == 'AJUSTE_SALIDA':
        cantidad_final = -cantidad_input
        
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            registrar_movimiento_kardex(
                cursor, 
                producto_id, 
                tipo, 
                cantidad_final, 
                nota, 
                current_user.id
            )
            db.commit()
            flash("Movimiento registrado correctamente.", "success")
    except Exception as e:
        db.rollback()
        flash(f"Error: {e}", "danger")
        
    return redirect(url_for('inventario.lista_inventario'))


@inventario_bp.route('/historial/<int:producto_id>')
@login_required
def ver_kardex_producto(producto_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # Info del producto
        cursor.execute("SELECT nombre, stock_actual FROM productos WHERE id = %s", (producto_id,))
        prod = cursor.fetchone()
        
        # Historial
        cursor.execute("""
            SELECT k.*, u.nombres as usuario
            FROM kardex k
            LEFT JOIN empleados u ON k.usuario_id = u.id
            WHERE k.producto_id = %s
            ORDER BY k.fecha DESC
        """, (producto_id,))
        movimientos = cursor.fetchall()
        
    return render_template('inventario/kardex_detalle.html', prod=prod, movimientos=movimientos)