import os
import requests
import json
from flask import current_app

class GeminiCRM:
    """
    Servicio para interactuar con Google Gemini para la generación de mensajes personalizados.
    """
    def __init__(self):
        self.api_key = os.environ.get('GEMINI_API_KEY')
        self.model = "gemini-2.0-flash"
        self.url = f"https://generativelanguage.googleapis.com/v1/models/{self.model}:generateContent?key={self.api_key}"

    def generar_mensaje_whatsapp(self, cliente_data):
        """
        Genera un mensaje de WhatsApp persuasivo y personalizado basado en el perfil del cliente.
        cliente_data: dict con {nombre, ultimo_servicio, fecha_ultima_visita, puntos, notas, motivo_alerta}
        """
        if not self.api_key:
            return "⚠️ Error: GEMINI_API_KEY no configurada. Configure la variable de entorno para usar IA."

        prompt = f"""
        Actúa como un recepcionista experto en marketing para una barbería/studio de belleza de alta gama llamado 'JV Studio'.
        Tu objetivo es redactar un mensaje de WhatsApp para el cliente que sea cálido, profesional, no invasivo y muy personalizado.
        
        Datos del Cliente:
        - Nombre: {cliente_data['nombre']}
        - Motivo del contacto: {cliente_data['motivo_alerta']}
        - Último servicio realizado: {cliente_data['ultimo_servicio']}
        - Fecha de última visita: {cliente_data['fecha_ultima_visita']}
        - Puntos de fidelidad acumulados: {cliente_data['puntos']}
        - Notas especiales del cliente: {cliente_data.get('notas', 'Sin notas')}
        
        Instrucciones:
        1. Usa un tono cercano (puedes usar emojis con moderación).
        2. Menciona de forma natural su último servicio o sus puntos acumulados si ayuda a la persuasión.
        3. Si es por cumpleaños, sé festivo.
        4. Si es porque no nos visita hace mucho, dile que le extrañamos.
        5. El mensaje debe ser CORTO (máximo 3 párrafos cortos).
        6. Agrega un llamado a la acción (CTA) claro al final (ej: "¿Te reservamos un espacio para esta semana?").
        7. Responde ÚNICAMENTE con el texto del mensaje sugerido. No agregues prefijos como "Mensaje sugerido:".
        """

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        try:
            response = requests.post(self.url, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                # Extraer texto de la respuesta de Gemini
                text = data['candidates'][0]['content']['parts'][0]['text'].strip()
                return text
            else:
                return f"Error en API Gemini ({response.status_code}): {response.text}"
        except Exception as e:
            return f"Error de conexión con IA: {str(e)}"
