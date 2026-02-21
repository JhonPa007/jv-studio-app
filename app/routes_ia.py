import os
import json
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required

ia_bp = Blueprint('ia', __name__, url_prefix='/ia')

# Ruta para el archivo JSON donde guardaremos los textos
def get_data_filepath():
    # Store inside an 'app/data' folder
    data_dir = os.path.join(current_app.root_path, 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'ia_conocimiento.json')

# Plantillas iniciales por defecto basándose en mejores prácticas
DEFAULT_CONTENT = {
    "reservas": """# 🤖 Base de Conocimiento - Agente Virtual (Módulo Reservas)

## 📌 Reglas de Negocio
- El cliente **SIEMPRE** debe dejar un adelanto del 50% para que su reserva sea procesada.
- El tiempo de tolerancia para llegar a la cita es de **15 minutos**. Pasado ese tiempo, la cita puede cancelarse.
- Las cancelaciones o reprogramaciones deben hacerse con **2 horas de anticipación**.

## 📞 Atención al Cliente (Estilo de Respuesta)
- Sé amable, profesional y directo.
- Si te piden agendar, solicita estos datos uno por uno:
  1. Nombre completo
  2. Servicio que desea
  3. Día y hora de preferencia
  4. Barber o profesional de su elección (opcional)

## 💬 Preguntas Frecuentes (FAQ)
**Pregunta:** ¿Cómo puedo agendar una cita?
**Respuesta:** ¡Hola! Claro que sí, para agendar tu cita necesito que me brindes tu nombre completo, el servicio que deseas realizarte, y la fecha/hora en la que te gustaría asistir.

**Pregunta:** ¿Puedo cancelar mi cita?
**Respuesta:** Sí puedes cancelar, pero recuerda que debes avisarnos con un mínimo de 2 horas de anticipación para poder reasignar tu espacio.""",

    "servicios": """# 🤖 Base de Conocimiento - Agente Virtual (Módulo Servicios)

## 📌 Catálogo General
Aquí tienes un resumen de nuestros principales servicios. Si el cliente pregunta por uno de ellos, ofrece enviarle nuestro catálogo completo o detalla el precio si pregunta específicamente.

- **Corte de Cabello Clásico:** S/ 35.00
- **Barba y Bigote:** S/ 20.00
- **Corte + Barba (Combo):** S/ 50.00
- **Tinte / Colorimetría:** Desde S/ 80.00 (requiere evaluación presencial).

## 📞 Atención al Cliente (Estilo de Respuesta)
- No inventes precios. Si un precio dice "Desde...", indícale al cliente que el precio final depende de la evaluación del barbero.
- Si te preguntan por un servicio que no está en la lista, responde educadamente que actualmente no brindamos ese servicio pero que estaremos encantados de atenderle con [insertar servicio similar].

## 💬 Preguntas Frecuentes (FAQ)
**Pregunta:** ¿Hacen peinados para eventos especiales?
**Respuesta:** ¡Hola! Por supuesto, realizamos peinados y perfilados para eventos. Te sugerimos agendar una cita de evaluación para ver qué estilo buscas y darte una cotización exacta.""",

    "productos": """# 🤖 Base de Conocimiento - Agente Virtual (Módulo Productos)

## 📌 Política de Productos
- Solo vendemos productos originales y garantizados.
- Realizamos ventas tanto en tienda física (Jr. Andahuaylas 220) como por delivery.
- Envíos por delivery tienen un costo adicional dependiendo del distrito (Aprox. S/ 10.00 a S/ 15.00).

## 📦 Productos Destacados
- **Cera Mate:** S/ 45.00 - Ideal para peinados estructurados sin brillo.
- **Aceite para Barba:** S/ 35.00 - Hidrata y estimula el crecimiento.
- **Shampoo Especializado:** S/ 50.00 - Para el cuidado diario libre de sal.

## 💬 Preguntas Frecuentes (FAQ)
**Pregunta:** ¿Hacen envíos a provincia?
**Respuesta:** Por el momento nuestros envíos están centralizados en Lima Metropolitana. Sin embargo, si deseas hacer una compra al por mayor, podríamos coordinar un envío por agencia.

**Pregunta:** ¿Tienen garantía sus productos?
**Respuesta:** Todos nuestros productos cuentan con garantía de calidad. Si presentas algún inconveniente o reacción desfavorable, puedes acercarte directamente a nuestro Studio para revisarlo."""
}

@ia_bp.route('/docs')
@login_required
def ver_documentacion():
    return render_template('ia/gestion_conocimiento.html')

@ia_bp.route('/api/docs/<modulo>', methods=['GET'])
@login_required
def obtener_documento(modulo):
    filepath = get_data_filepath()
    if not os.path.exists(filepath):
        # Si no existe, crearlo con el contenido por defecto
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONTENT, f, ensure_ascii=False, indent=4)
        data = DEFAULT_CONTENT
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
    # Asegurarnos que el modulo exista, si no, crearle una entrada vacía
    content = data.get(modulo, f"# 🤖 Base de Conocimiento - {modulo.capitalize()}\n\nEscribe aquí la documentación para este módulo.")
    
    return jsonify({'content': content})

@ia_bp.route('/api/docs/<modulo>', methods=['POST'])
@login_required
def guardar_documento(modulo):
    filepath = get_data_filepath()
    
    # Leer archivo actual
    if not os.path.exists(filepath):
        data = DEFAULT_CONTENT.copy()
    else:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
    # Obtener contenido nuevo
    nuevo_contenido = request.json.get('content', '')
    
    # Actualizar y guardar
    data[modulo] = nuevo_contenido
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    return jsonify({'mensaje': 'Documentación guardada exitosamente'})
