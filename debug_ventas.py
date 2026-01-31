
from app import create_app
from app.db import get_db
import psycopg2.extras
import sys

sys.stdout.reconfigure(encoding='utf-8')

app = create_app()

with app.app_context():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("Testing Empleados Query...")
        try:
            cursor.execute("SELECT id, nombre_display FROM empleados WHERE activo=TRUE ORDER BY nombre_display")
            emps = cursor.fetchall()
            print(f"Empleados found: {len(emps)}")
            if emps:
                print(f"First emp: {emps[0]}")
        except Exception as e:
            print(f"❌ EMPLEADOS QUERY FAILED: {e}")
            db.rollback()

    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        print("\nTesting Ventas Query...")
        try:
            base_sql = """
                SELECT 
                    v.id AS venta_id, 
                    v.fecha_venta, 
                    v.monto_final_venta, 
                    v.estado_pago,
                    v.tipo_comprobante,
                    v.estado_sunat,
                    v.estado_sunat,
                    v.serie_comprobante, 
                    v.numero_comprobante,
                    e.nombre_display AS empleado_nombre,
                    COALESCE(CONCAT(c.razon_social_nombres, ' ', c.apellidos), 'Cliente Varios') AS cliente_nombre
                FROM ventas v
                JOIN empleados e ON v.empleado_id = e.id
                LEFT JOIN clientes c ON v.cliente_receptor_id = c.id
                WHERE 1=1
                LIMIT 5
            """
            cursor.execute(base_sql)
            ventas = cursor.fetchall()
            print(f"Ventas found: {len(ventas)}")
        except Exception as e:
            print(f"❌ VENTAS QUERY FAILED: {e}")
            db.rollback()
