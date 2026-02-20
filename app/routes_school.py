
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
from datetime import date, datetime, timedelta
from .db import get_db

# Definimos el Blueprint para la Escuela
school_bp = Blueprint('school', __name__, url_prefix='/school')

# ==============================================================================
# VISTAS (HTML)
# ==============================================================================

@school_bp.route('/students')
@login_required
def view_students():
    return render_template('school/panel_alumno.html')

@school_bp.route('/payments/manage')
@login_required
def view_payments():
    return render_template('school/caja_pagos.html')

@school_bp.route('/courses')
@login_required
def view_courses():
    return render_template('school/gestion_cursos.html')

# ==============================================================================
# HELPERS
# ==============================================================================

def _generar_codigo_alumno(cursor):
    """Genera un código de alumno tipo AL-2026-001"""
    anio_actual = date.today().year
    
    # Buscar el último código de este año
    cursor.execute("""
        SELECT codigo_alumno FROM escuela_alumnos 
        WHERE codigo_alumno LIKE %s 
        ORDER BY codigo_alumno DESC LIMIT 1
    """, (f'AL-{anio_actual}-%',))
    
    ultimo = cursor.fetchone()
    
    if ultimo:
        # Extraer secuencia: AL-2026-001 -> 001
        try:
            ultimo_cod = ultimo['codigo_alumno'] # RealDictRow access
            secuencia = int(ultimo_cod.split('-')[-1])
            nueva_secuencia = secuencia + 1
        except:
            nueva_secuencia = 1
    else:
        nueva_secuencia = 1
        
    return f"AL-{anio_actual}-{nueva_secuencia:03d}"

def _generar_codigo_recibo(cursor):
    """Genera un código de recibo tipo REC-00001"""
    cursor.execute("SELECT codigo_recibo FROM escuela_pagos ORDER BY id DESC LIMIT 1")
    ultimo = cursor.fetchone()
    
    if ultimo and ultimo['codigo_recibo']:
        try:
            # Asumiendo formato REC-XXXXX
            secuencia = int(ultimo['codigo_recibo'].split('-')[-1])
            nueva_secuencia = secuencia + 1
        except:
            nueva_secuencia = 1
    else:
        nueva_secuencia = 1
        
    return f"REC-{nueva_secuencia:05d}"

# ==============================================================================
# ENDPOINTS: CONFIGURACIÓN (Cursos / Grupos)
# ==============================================================================

@school_bp.route('/api/courses', methods=['GET'])
@login_required
def list_courses():
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM escuela_cursos WHERE activo = TRUE ORDER BY nombre")
        cursos = cursor.fetchall()
    return jsonify(cursos)

@school_bp.route('/api/groups', methods=['GET'])
@login_required
def list_groups():
    curso_id = request.args.get('curso_id')
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        if curso_id:
            cursor.execute("""
                SELECT g.*, c.nombre as curso_nombre 
                FROM escuela_grupos g
                JOIN escuela_cursos c ON g.curso_id = c.id
                WHERE g.activo = TRUE AND g.curso_id = %s
                ORDER BY g.codigo_grupo
            """, (curso_id,))
        else:
            cursor.execute("""
                SELECT g.*, c.nombre as curso_nombre 
                FROM escuela_grupos g
                JOIN escuela_cursos c ON g.curso_id = c.id
                WHERE g.activo = TRUE
                ORDER BY g.codigo_grupo
            """)
        grupos = cursor.fetchall()
    return jsonify(grupos)

@school_bp.route('/api/courses', methods=['POST'])
@login_required
def create_course():
    data = request.json
    nombre = data.get('nombre')
    matricula = data.get('costo_matricula', 0)
    mensualidad = data.get('costo_mensualidad', 0)
    duracion = data.get('duracion_meses', 1)
    
    if not nombre:
        return jsonify({'error': 'Nombre es obligatorio'}), 400
        
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO escuela_cursos (nombre, costo_matricula, costo_mensualidad, duracion_meses)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (nombre, matricula, mensualidad, duracion))
            new_id = cursor.fetchone()[0]
            db.commit()
            return jsonify({'message': 'Curso creado', 'id': new_id})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500

@school_bp.route('/api/groups', methods=['POST'])
@login_required
def create_group():
    data = request.json
    codigo = data.get('codigo_grupo')
    curso_id = data.get('curso_id')
    fecha = data.get('fecha_inicio')
    dias_clase = data.get('dias_clase', '')
    hora_inicio = data.get('hora_inicio')
    hora_fin = data.get('hora_fin')
    
    if not codigo or not curso_id:
        return jsonify({'error': 'Faltan datos'}), 400
        
    db = get_db()
    try:
        with db.cursor() as cursor:
            cursor.execute("""
                INSERT INTO escuela_grupos (codigo_grupo, curso_id, fecha_inicio, dias_clase, hora_inicio, hora_fin)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (codigo, curso_id, fecha, dias_clase, hora_inicio, hora_fin))
            new_id = cursor.fetchone()[0]
            db.commit()
            return jsonify({'message': 'Grupo creado', 'id': new_id})
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500

# ==============================================================================
# ENDPOINT: REGISTRO DE ALUMNO (NUCLEO)
# ==============================================================================

@school_bp.route('/api/students/register', methods=['POST'])
@login_required
def register_student():
    data = request.json
    
    # Datos del Formulario
    nombres = data.get('nombres')
    dni = data.get('dni')
    curso_id = data.get('curso_id')
    grupo_id = data.get('grupo_id')
    
    # Opcionales
    apellidos = data.get('apellidos', '')
    telefono = data.get('telefono', '')
    fecha_inicio = data.get('fecha_inicio') # YYYY-MM-DD
    
    if not nombres or not dni or not curso_id:
        return jsonify({'error': 'Faltan datos obligatorios'}), 400

    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Obtener info del Curso (para costos y duración defaults)
            cursor.execute("SELECT * FROM escuela_cursos WHERE id = %s", (curso_id,))
            curso = cursor.fetchone()
            if not curso:
                return jsonify({'error': 'Curso no encontrado'}), 404
            
            # 2. Generar Código
            codigo_alumno = _generar_codigo_alumno(cursor)
            
            # 3. Insertar Alumno
            cursor.execute("""
                INSERT INTO escuela_alumnos 
                (codigo_alumno, nombres, apellidos, dni, telefono, curso_id, grupo_id, fecha_inicio_clases,
                 costo_matricula_acordado, costo_mensualidad_acordada, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Activo')
                RETURNING id
            """, (
                codigo_alumno, nombres, apellidos, dni, telefono, curso_id, grupo_id, fecha_inicio,
                curso['costo_matricula'], curso['costo_mensualidad']
            ))
            alumno_id = cursor.fetchone()['id']
            
            # 4. GENERACIÓN DE CUOTAS (PLAN DE PAGOS)
            # A. Matrícula (Siempre va primero, orden 0)
            cursor.execute("""
                INSERT INTO escuela_cuotas 
                (alumno_id, concepto, monto_original, monto_pagado, saldo, fecha_vencimiento, estado, orden_pago)
                VALUES (%s, 'Matrícula', %s, 0.00, %s, %s, 'Pendiente', 0)
            """, (alumno_id, curso['costo_matricula'], curso['costo_matricula'], fecha_inicio))
            
            # B. Mensualidades
            duracion = curso['duracion_meses']
            mensualidad = curso['costo_mensualidad']
            f_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
            
            for i in range(1, duracion + 1):
                # Calcular vencimiento (simple: +30 días por mes, o mismo día del siguiente mes)
                # Aproximación simple: sumar 30 días * i
                # Mejor aproximación: Mismo día del mes siguiente
                
                # Logic to add months
                mes_venc = f_inicio_dt.month + i
                anio_venc = f_inicio_dt.year + (mes_venc - 1) // 12
                mes_venc = (mes_venc - 1) % 12 + 1
                dia_venc = min(f_inicio_dt.day, 28) # Simplificación para no romper feb
                
                f_venc = date(anio_venc, mes_venc, dia_venc)
                
                cursor.execute("""
                    INSERT INTO escuela_cuotas 
                    (alumno_id, concepto, monto_original, monto_pagado, saldo, fecha_vencimiento, estado, orden_pago)
                    VALUES (%s, %s, %s, 0.00, %s, %s, 'Pendiente', %s)
                """, (alumno_id, f"Mensualidad {i}", mensualidad, mensualidad, f_venc, i))
            
            db.commit()
            return jsonify({'mensaje': 'Alumno registrado exitosamente', 'codigo': codigo_alumno, 'id': alumno_id})

    except Exception as e:
        db.rollback()
        print(f"Error registrando alumno: {e}")
        return jsonify({'error': str(e)}), 500

@school_bp.route('/api/students', methods=['GET'])
@login_required
def list_students():
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Join with courses and groups to get names/codes instead of just IDs
            cursor.execute("""
                SELECT a.id, a.codigo_alumno, a.nombres, a.apellidos, a.dni, a.estado,
                       c.nombre as curso_nombre, g.codigo_grupo
                FROM escuela_alumnos a
                LEFT JOIN escuela_cursos c ON a.curso_id = c.id
                LEFT JOIN escuela_grupos g ON a.grupo_id = g.id
                ORDER BY a.fecha_inscripcion DESC
            """)
            alumnos = cursor.fetchall()
            return jsonify([dict(a) for a in alumnos])
    except Exception as e:
        print(f"Error listing students: {e}")
        return jsonify({'error': str(e)}), 500

@school_bp.route('/api/students/search', methods=['GET'])
@login_required
def search_student():
    """Busca un alumno por código, DNI o Nombres"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Parámetro de búsqueda vacío'}), 400
        
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Buscar coincidencia exacta por DNI o Código, o LIKE por nombres/apellidos/teléfono
            cursor.execute("""
                SELECT id 
                FROM escuela_alumnos 
                WHERE codigo_alumno ILIKE %s 
                   OR dni = %s 
                   OR telefono = %s
                   OR (nombres || ' ' || apellidos) ILIKE %s
                ORDER BY id DESC LIMIT 1
            """, (f"%{query}%", query, query, f"%{query}%"))
            result = cursor.fetchone()
            
            if result:
                return jsonify({'id': result['id']})
            else:
                return jsonify({'error': 'Alumno no encontrado'}), 404
    except Exception as e:
        print(f"Error searching student: {e}")
        return jsonify({'error': str(e)}), 500

# ==============================================================================
# ENDPOINT: ESTADO DE CUENTA
# ==============================================================================

@school_bp.route('/api/students/<int:student_id>/statement', methods=['GET'])
@login_required
def get_statement(student_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # 1. Datos Alumno
        cursor.execute("""
            SELECT a.*, c.nombre as curso_nombre, g.codigo_grupo
            FROM escuela_alumnos a
            LEFT JOIN escuela_cursos c ON a.curso_id = c.id
            LEFT JOIN escuela_grupos g ON a.grupo_id = g.id
            WHERE a.id = %s
        """, (student_id,))
        alumno = cursor.fetchone()
        
        if not alumno:
            return jsonify({'error': 'Alumno no encontrado'}), 404
            
        # 2. Cuotas (Cronograma)
        cursor.execute("""
            SELECT * FROM escuela_cuotas 
            WHERE alumno_id = %s 
            ORDER BY orden_pago ASC
        """, (student_id,))
        cuotas = cursor.fetchall()
        
        # 3. Pagos Realizados
        cursor.execute("""
            SELECT * FROM escuela_pagos 
            WHERE alumno_id = %s 
            ORDER BY fecha_pago DESC
        """, (student_id,))
        pagos = cursor.fetchall()
        
        # Calcular Totales Globales
        total_deuda = sum(c['monto_original'] for c in cuotas)
        total_pagado_global = sum(c['monto_pagado'] for c in cuotas)
        saldo_global = sum(c['saldo'] for c in cuotas)
        
        return jsonify({
            'alumno': dict(alumno),
            'cuotas': [dict(c) for c in cuotas],
            'pagos': [dict(p) for p in pagos],
            'resumen': {
                'total_curso': total_deuda,
                'total_pagado': total_pagado_global,
                'saldo_pendiente': saldo_global
            }
        })

# ==============================================================================
# ENDPOINT: REGISTRAR PAGO (CASCADA)
# ==============================================================================

@school_bp.route('/api/payments', methods=['POST'])
@login_required
def register_payment():
    data = request.json
    alumno_id = data.get('alumno_id')
    monto = float(data.get('monto', 0))
    metodo_pago = data.get('metodo_pago', 'Efectivo')
    observaciones = data.get('observaciones', '')
    
    # Custom Date handling
    fecha_pago_str = data.get('fecha_pago')
    if fecha_pago_str:
        try:
            # Parse datetime-local format: YYYY-MM-DDTHH:MM
            fecha_pago_real = datetime.strptime(fecha_pago_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            fecha_pago_real = datetime.now()
    else:
        fecha_pago_real = datetime.now()
    
    if not alumno_id or monto <= 0:
        return jsonify({'error': 'Datos inválidos'}), 400
        
    db = get_db()
    try:
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # 1. Registrar Cabecera de Pago
            codigo_recibo = _generar_codigo_recibo(cursor)
            
            cursor.execute("""
                INSERT INTO escuela_pagos 
                (alumno_id, monto, fecha_pago, metodo_pago, codigo_recibo, usuario_id, observaciones)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (alumno_id, monto, fecha_pago_real, metodo_pago, codigo_recibo, current_user.id, observaciones))
            pago_id = cursor.fetchone()['id']
            
            # 2. LÓGICA DE CASCADA (WATERFALL)
            # Buscar cuotas pendientes ordenadas por prioridad (orden_pago)
            cursor.execute("""
                SELECT id, concepto, saldo, orden_pago 
                FROM escuela_cuotas 
                WHERE alumno_id = %s AND estado != 'Completo'
                ORDER BY orden_pago ASC
            """, (alumno_id,))
            cuotas_pendientes = cursor.fetchall()
            
            remanente = monto
            detalles_generados = []
            
            for cuota in cuotas_pendientes:
                if remanente <= 0:
                    break
                    
                saldo_cuota = float(cuota['saldo'])
                
                # Cuánto aplicamos a esta cuota? El menor entre lo que tengo y lo que debo
                monto_aplicar = min(remanente, saldo_cuota)
                
                if monto_aplicar > 0:
                    # A. Crear Detalle
                    cursor.execute("""
                        INSERT INTO escuela_pagos_detalle (pago_id, cuota_id, monto_aplicado)
                        VALUES (%s, %s, %s)
                    """, (pago_id, cuota['id'], monto_aplicar))
                    
                    # B. Actualizar Cuota
                    nuevo_pagado_cuota = monto_aplicar # + lo que ya tenía? No, el UPDATE debe sumar
                    
                    # Determinar nuevo estado
                    # Si cubrimos todo el saldo ==> Completo
                    # Si cubrimos parte ==> Parcial
                    # Nota: saldo_cuota era el saldo pendiente. Si monto_aplicar == saldo_cuota, queda en 0.
                    
                    nuevo_estado = 'Completo' if (abs(saldo_cuota - monto_aplicar) < 0.01) else 'Parcial'
                    
                    cursor.execute("""
                        UPDATE escuela_cuotas 
                        SET monto_pagado = monto_pagado + %s,
                            saldo = saldo - %s,
                            estado = %s
                        WHERE id = %s
                    """, (monto_aplicar, monto_aplicar, nuevo_estado, cuota['id']))
                    
                    detalles_generados.append({
                        'concepto': cuota['concepto'],
                        'monto': monto_aplicar,
                        'estado_final': nuevo_estado
                    })
                    
                    remanente -= monto_aplicar
            
            # 3. Manejo de Saldo a Favor (Si sobra dinero después de pagar TODO)
            if remanente > 0:
                # Opcional: Crear una cuota 'Crédito a Favor' o dejarlo en la última cuota?
                # Por ahora, simplemente lo agregamos a las observaciones o lo ignoramos (riesgo)
                # Lo mejor: Crear nota en observaciones del pago
                cursor.execute("""
                    UPDATE escuela_pagos 
                    SET observaciones = observaciones || ' [Saldo a favor: S/ ' || %s || ']'
                    WHERE id = %s
                """, (remanente, pago_id))
            
            db.commit()
            
            return jsonify({
                'mensaje': 'Pago registrado exitosamente',
                'recibo': codigo_recibo,
                'pago_id': pago_id,
                'distribucion': detalles_generados,
                'remanente': remanente
            })

    except Exception as e:
        db.rollback()
        print(f"Error procesando pago: {e}")
        return jsonify({'error': str(e)}), 500

# ==============================================================================
# ENDPOINT: VISTA DE RECIBO (HTML)
# ==============================================================================
@school_bp.route('/recibo/<int:pago_id>')
@login_required
def print_receipt(pago_id):
    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        # Cabecera
        cursor.execute("""
            SELECT p.*, a.nombres, a.apellidos, a.dni, a.codigo_alumno, c.nombre as curso_nombre
            FROM escuela_pagos p
            JOIN escuela_alumnos a ON p.alumno_id = a.id
            LEFT JOIN escuela_cursos c ON a.curso_id = c.id
            WHERE p.id = %s
        """, (pago_id,))
        pago = cursor.fetchone()
        
        if not pago: return "Recibo no encontrado", 404
        
        # Detalles
        cursor.execute("""
            SELECT d.monto_aplicado, cu.concepto
            FROM escuela_pagos_detalle d
            JOIN escuela_cuotas cu ON d.cuota_id = cu.id
            WHERE d.pago_id = %s
        """, (pago_id,))
        detalles = cursor.fetchall()
        
    return render_template('school/recibo_impresion.html', pago=pago, detalles=detalles)
