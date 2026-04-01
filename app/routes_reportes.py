import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, flash, current_app, jsonify
from flask_login import login_required, current_user
from .db import get_db
from .decorators import admin_required

reportes_bp = Blueprint('reportes', __name__)

@reportes_bp.route('/reportes/ingresos-egresos', methods=['GET'])
@login_required
@admin_required
def ingresos_egresos():
    """Reporte detallado de Ingresos y Egresos (Flujo de Caja)."""
    db_conn = get_db()
    fecha_inicio_str = request.args.get('fecha_inicio')
    fecha_fin_str = request.args.get('fecha_fin')
    sucursal_id_str = request.args.get('sucursal_id')
    
    # Valores por defecto: Mes actual y sucursal de la sesión
    hoy = datetime.now()
    if not fecha_inicio_str:
        fecha_inicio_str = hoy.replace(day=1).strftime('%Y-%m-%d')
    if not fecha_fin_str:
        fecha_fin_str = hoy.strftime('%Y-%m-%d')
    if not sucursal_id_str:
        from flask import session
        sucursal_id_str = str(session.get('sucursal_id', ''))

    sucursales_activas = []
    resultados = None

    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("SELECT id, nombre FROM sucursales WHERE activo = TRUE ORDER BY nombre")
            sucursales_activas = cursor.fetchall()
            
            if sucursal_id_str:
                sucursal_id = int(sucursal_id_str)
                f_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
                f_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
                
                # 1. Ingresos (Ventas)
                cursor.execute("""
                    SELECT 'Ventas Generales' as concepto, SUM(monto_final_venta) as total, 'Ingreso' as tipo
                    FROM ventas
                    WHERE sucursal_id = %s AND DATE(fecha_venta) BETWEEN %s AND %s AND estado_pago != 'Anulado'
                """, (sucursal_id, f_inicio, f_fin))
                ventas_total = cursor.fetchone()
                
                # Movimientos manuales de ingreso
                cursor.execute("""
                    SELECT concepto, SUM(monto) as total, 'Ingreso' as tipo 
                    FROM movimientos_caja mc 
                    JOIN caja_sesiones cs ON mc.caja_sesion_id = cs.id
                    WHERE cs.sucursal_id = %s AND mc.tipo = 'Ingreso' AND DATE(mc.fecha) BETWEEN %s AND %s 
                    GROUP BY concepto
                """, (sucursal_id, f_inicio, f_fin))
                mov_ingresos = cursor.fetchall()

                # 2. Egresos (Gastos Operativos, Planillas, Movimientos extra)
                cursor.execute("""
                    SELECT cg.nombre as concepto, SUM(g.monto) as total, 'Egreso' as tipo
                    FROM gastos g
                    JOIN categorias_gastos cg ON g.categoria_gasto_id = cg.id
                    WHERE g.sucursal_id = %s AND DATE(g.fecha) BETWEEN %s AND %s
                    GROUP BY cg.nombre
                """, (sucursal_id, f_inicio, f_fin))
                gastos = cursor.fetchall()
                
                # Compras
                cursor.execute("""
                    SELECT 'Compras a Proveedores' as concepto, SUM(monto_total) as total, 'Egreso' as tipo
                    FROM compras
                    WHERE sucursal_id = %s AND DATE(fecha_compra) BETWEEN %s AND %s
                """, (sucursal_id, f_inicio, f_fin))
                compras = cursor.fetchone()
                
                mov_egresos = [] # Simplificado para arrancar

                flujo = []
                # Concatenamos cuidando los nulos
                if ventas_total and ventas_total['total']: flujo.append(ventas_total)
                for i in mov_ingresos: 
                    if i['total']: flujo.append(i)
                for g in gastos: 
                    if g['total']: flujo.append(g)
                if compras and compras['total']: flujo.append(compras)
                
                total_ingresos = sum(f['total'] for f in flujo if f['tipo'] == 'Ingreso')
                total_egresos = sum(f['total'] for f in flujo if f['tipo'] == 'Egreso')
                utilidad = total_ingresos - total_egresos
                
                resultados = {
                    "flujo": flujo,
                    "total_ingresos": total_ingresos,
                    "total_egresos": total_egresos,
                    "utilidad": utilidad
                }
    except Exception as e:
        flash(f"Error generando reporte: {e}", "danger")
        current_app.logger.error(f"Error en ingresos_egresos: {e}")

    return render_template(
        'reportes/ingresos_egresos.html',
        titulo_pagina="Reporte de Ingresos y Egresos",
        filtros={"fecha_inicio": fecha_inicio_str, "fecha_fin": fecha_fin_str, "sucursal_id": sucursal_id_str},
        sucursales=sucursales_activas,
        resultados=resultados
    )

@reportes_bp.route('/reportes/balance-general', methods=['GET'])
@login_required
@admin_required
def balance_general():
    """Balance General (Activos y Pasivos Corrientes)."""
    db_conn = get_db()
    
    activo_efectivo_estimado = 0
    pasivo_proveedores = 0
    pasivo_comisiones = 0
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Activo: Cajas abiertas (monto final calculable)
            cursor.execute("SELECT SUM(efectivo_actual) as total_cajas FROM caja_sesiones WHERE estado='Abierta'")
            row_caja = cursor.fetchone()
            if row_caja and row_caja['total_cajas']:
                activo_efectivo_estimado = row_caja['total_cajas']
                
            # Pasivos: Proveedores (Compras pendientes de pago)
            cursor.execute("SELECT SUM(monto_total) as deuda_prov FROM compras WHERE estado_pago = 'Pendiente de Pago'")
            row_prov = cursor.fetchone()
            if row_prov and row_prov['deuda_prov']:
                pasivo_proveedores = row_prov['deuda_prov']
                
            # Pasivos: Empleados (Ventas cobradas no liquidadas en planilla)
            # Esto es una estimación sumando las comisiones_servicios de items de venta no apagados.
            # En planilla real se usa la marca pagado_en_planilla, asumiremos True/False o si no el total
            # del periodo no pagado. Por ahora sumamos comisiones donde comision_id is null o similar.
            cursor.execute("""
                SELECT SUM(vi.comision_empleado) as comisiones_pendientes
                FROM venta_items vi
                JOIN ventas v ON vi.venta_id = v.id
                WHERE v.estado_pago != 'Anulado' AND vi.pagado_en_planilla = FALSE
            """)
            row_comis = cursor.fetchone()
            if row_comis and row_comis['comisiones_pendientes']:
                pasivo_comisiones = row_comis['comisiones_pendientes']
                
    except Exception as e:
        flash(f"Error calculando el balance: {e}", "danger")
        current_app.logger.error(f"Error en balance general: {e}")

    total_activos = activo_efectivo_estimado
    total_pasivos = pasivo_proveedores + pasivo_comisiones
    patrimonio = total_activos - total_pasivos

    return render_template(
        'reportes/balance_general.html',
        titulo_pagina="Balance General",
        activos=activo_efectivo_estimado,
        pasivo_proveedores=pasivo_proveedores,
        pasivo_comisiones=pasivo_comisiones,
        total_activos=total_activos,
        total_pasivos=total_pasivos,
        patrimonio=patrimonio
    )

@reportes_bp.route('/reportes/dashboard-financiero', methods=['GET'])
@login_required
@admin_required
def dashboard_financiero():
    """Dashboard visual con KPIs y gráficos financieros."""
    # Para arrancar la vista, podemos mandar data en blanco a ser requerida via AJAX 
    # o prepararla directamente aquí. Prepararemos un mockup de data por meses inicial.
    
    db_conn = get_db()
    datos_mensuales = []
    
    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Consultar últimos 6 meses (Simplificado)
            cursor.execute("""
                SELECT 
                    TO_CHAR(DATE_TRUNC('month', fecha_venta), 'YYYY-MM') as mes,
                    SUM(monto_final_venta) as ingresos
                FROM ventas
                WHERE estado_pago != 'Anulado'
                GROUP BY DATE_TRUNC('month', fecha_venta)
                ORDER BY mes DESC
                LIMIT 6
            """)
            ingresos_mes = {row['mes']: float(row['ingresos']) for row in cursor.fetchall()}
            
            cursor.execute("""
                SELECT 
                    TO_CHAR(DATE_TRUNC('month', fecha), 'YYYY-MM') as mes,
                    SUM(monto) as egresos
                FROM gastos
                GROUP BY DATE_TRUNC('month', fecha)
                ORDER BY mes DESC
                LIMIT 6
            """)
            egresos_mes = {row['mes']: float(row['egresos']) for row in cursor.fetchall()}
            
            # Combinar datos
            meses_set = set(list(ingresos_mes.keys()) + list(egresos_mes.keys()))
            meses_ordenados = sorted(list(meses_set))
            
            for m in meses_ordenados:
                ing = ingresos_mes.get(m, 0.0)
                egr = egresos_mes.get(m, 0.0)
                datos_mensuales.append({
                    "mes": m,
                    "ingresos": ing,
                    "egresos": egr,
                    "utilidad": ing - egr
                })
                
    except Exception as e:
        flash(f"Error generando dashboard: {e}", "danger")
        
    return render_template(
        'reportes/dashboard_financiero.html',
        titulo_pagina="Dashboard Financiero",
        datos_mensuales=datos_mensuales
    )

@reportes_bp.route('/reportes/registro-contable', methods=['GET'])
@login_required
@admin_required
def registro_contable_mensual():
    """Reporte formal de Registro Contable (Ventas y Compras) p/ SUNAT."""
    db_conn = get_db()
    periodo_str = request.args.get('periodo') # Formato: YYYY-MM
    
    # Valores por defecto: Mes actual
    hoy = datetime.now()
    if not periodo_str:
        periodo_str = hoy.strftime('%Y-%m')

    ventas = []
    compras = []
    totales = {
        "ventas_subtotal": 0, "ventas_igv": 0, "ventas_total": 0,
        "compras_subtotal": 0, "compras_igv": 0, "compras_total": 0
    }

    try:
        with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Ventas Válidas (Excluye Notas de Venta internas y Anuladas)
            cursor.execute("""
                SELECT 
                    v.fecha_venta as fecha, 
                    v.tipo_comprobante, 
                    v.serie_comprobante as serie, 
                    v.numero_comprobante as numero,
                    v.monto_final_venta as total,
                    COALESCE(c.razon_social_nombres, 'CLIENTES VARIOS') as cliente_nombre,
                    COALESCE(c.numero_documento, '00000000') as cliente_doc,
                    COALESCE(tc.codigo_sunat, '00') as tipo_doc_sunat
                FROM ventas v
                LEFT JOIN clientes c ON v.cliente_facturacion_id = c.id
                LEFT JOIN (SELECT 'DNI' as tipo, '1' as codigo_sunat UNION SELECT 'RUC', '6' UNION SELECT 'Otro', '0') tc 
                     ON c.tipo_documento = tc.tipo
                WHERE v.estado_pago != 'Anulado' 
                AND v.tipo_comprobante IN ('Factura Electrónica', 'Boleta Electrónica')
                AND TO_CHAR(v.fecha_venta, 'YYYY-MM') = %s
                ORDER BY v.fecha_venta ASC
            """, (periodo_str,))
            ventas_db = cursor.fetchall()
            
            for v in ventas_db:
                total = float(v['total'])
                subtotal = total / 1.18
                igv = total - subtotal
                
                v['subtotal'] = subtotal
                v['igv'] = igv
                ventas.append(v)
                
                totales['ventas_subtotal'] += subtotal
                totales['ventas_igv'] += igv
                totales['ventas_total'] += total

            # 2. Compras
            cursor.execute("""
                SELECT 
                    c.fecha_compra as fecha, 
                    c.tipo_comprobante, 
                    c.serie_numero_comprobante as correlativo,
                    c.monto_subtotal as subtotal, 
                    c.monto_impuestos as igv, 
                    c.monto_total as total,
                    p.nombre_empresa as proveedor_nombre,
                    p.ruc as proveedor_ruc
                FROM compras c
                LEFT JOIN proveedores p ON c.proveedor_id = p.id
                WHERE TO_CHAR(c.fecha_compra, 'YYYY-MM') = %s
                ORDER BY c.fecha_compra ASC
            """, (periodo_str,))
            compras_db = cursor.fetchall()
            
            for comp in compras_db:
                compras.append(comp)
                totales['compras_subtotal'] += float(comp['subtotal'])
                totales['compras_igv'] += float(comp['igv'])
                totales['compras_total'] += float(comp['total'])

    except Exception as e:
        flash(f"Error generando registro contable: {e}", "danger")
        current_app.logger.error(f"Error en registro_contable_mensual: {e}")

    return render_template(
        'reportes/registro_contable.html',
        titulo_pagina="Registro Contable Mensual",
        ventas=ventas,
        compras=compras,
        totales=totales,
        periodo=periodo_str
    )
