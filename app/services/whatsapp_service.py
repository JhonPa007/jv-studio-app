import threading
from flask import current_app

def _enviar_mensaje_async(numero, mensaje):
    """
    Función interna que se ejecuta en segundo plano.
    Aquí es donde conectarás Twilio, Waha o Meta API en el futuro.
    """
    try:
        # --- AQUÍ IRÍA LA CONEXIÓN REAL CON WHATSAPP ---
        # Por ahora, simulamos el envío imprimiendo en la consola del servidor
        print(f"\n[WHATSAPP BACKGROUND] 📨 Enviando a {numero}:")
        print(f"---\n{mensaje}\n---\n")
        # -----------------------------------------------
    except Exception as e:
        print(f"❌ Error en servicio WhatsApp: {e}")

def enviar_alerta_reserva(cliente_tel, staff_tel, datos_cita):
    """
    Función principal para disparar las alertas.
    Se llama desde routes.py y no bloquea la respuesta al usuario.
    """
    # 1. Mensaje para el CLIENTE
    if cliente_tel:
        msg_cliente = (
            f"Hola *{datos_cita['cliente']}*! 👋\n"
            f"Tu reserva en *JV Studio* está confirmada.\n\n"
            f"📅 Fecha: {datos_cita['fecha']}\n"
            f"⏰ Hora: {datos_cita['hora']}\n"
            f"💇 Servicio: {datos_cita['servicio']}\n"
            f"📍 Especialista: {datos_cita['staff']}\n\n"
            f"¡Te esperamos!"
        )
        # Ejecutar en hilo paralelo (Fire & Forget)
        threading.Thread(target=_enviar_mensaje_async, args=(cliente_tel, msg_cliente)).start()

    # 2. Mensaje para el COLABORADOR (Staff)
    if staff_tel:
        msg_staff = (
            f"🔔 *Nueva Reserva Asignada*\n"
            f"👤 Cliente: {datos_cita['cliente']}\n"
            f"📅 {datos_cita['fecha']} - ⏰ {datos_cita['hora']}\n"
            f"✂️ {datos_cita['servicio']}"
        )
        threading.Thread(target=_enviar_mensaje_async, args=(staff_tel, msg_staff)).start()