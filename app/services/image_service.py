import cloudinary
import cloudinary.uploader
import os

def configurar_cloudinary(app):
    """
    Configura Cloudinary usando la variable de entorno o la configuración de la app.
    La librería lee automáticamente CLOUDINARY_URL, así que esto es principalmente
    para verificar que esté cargada o hacer configuraciones extra si hicieran falta.
    """
    # Cloudinary se autoconfigura si existe la variable de entorno CLOUDINARY_URL.
    # Si la estás pasando explícitamente en app.config, podrías hacer:
    cloudinary_url = app.config.get('CLOUDINARY_URL')
    if not cloudinary_url and not os.environ.get('CLOUDINARY_URL'):
        print("⚠️ Advertencia: No se detectó CLOUDINARY_URL. Las subidas fallarán.")
        return

def subir_imagen(archivo, carpeta="jv_studio_empleados", public_id_prefix=None):
    """
    Sube una imagen a Cloudinary.
    
    Args:
        archivo: El objeto file storage de Flask (request.files['...'])
        carpeta: Nombre de la carpeta en Cloudinary (default: jv_studio_empleados)
        public_id_prefix: Prefijo opcional para el nombre del archivo.
    
    Returns:
        str: URL segura (https) de la imagen subida, o None si falla.
    """
    if not archivo:
        return None
    
    try:
        # Configurar opciones de subida
        opciones = {
            "folder": carpeta,
            "resource_type": "image",
            # Transformaciones por defecto para ahorrar peso y estandarizar
            "transformation": [
                {"width": 800, "crop": "limit"}, # No más grandes de 800px
                {"quality": "auto", "fetch_format": "auto"} # Optimización automática
            ]
        }
        
        if public_id_prefix:
            # Usar un nombre de archivo predecible si se desea, o dejar que Cloudinary genere uno random
            # Para evitar conflictos, Cloudinary añade caracteres random si no usas 'overwrite=True'
            opciones["public_id"] = f"{public_id_prefix}_{archivo.filename.split('.')[0]}"

        respuesta = cloudinary.uploader.upload(archivo, **opciones)
        
        return respuesta.get('secure_url')
    
    except Exception as e:
        print(f"❌ Error subiendo imagen a Cloudinary: {e}")
        return None
