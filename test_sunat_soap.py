
import os
import base64
from zeep import Client, Transport, Settings
from zeep.wsse.username import UsernameToken
from zeep.exceptions import Fault

# Configuración
WSDL_URL = r"d:\JV_Studio\jv_studio_app\app\sunat\billService_merged.wsdl"
RUC = "20614287561"
USER = "20614287561JHONPAJV"
PASS = "Jhon001*"

def test_connection():
    try:
        transport = Transport(timeout=10)
        settings = Settings(strict=False, xml_huge_tree=True)
        client = Client(wsdl=WSDL_URL, transport=transport, wsse=UsernameToken(USER, PASS), settings=settings)
        
        print("Intentando llamar a getStatus (con ticket falso para probar conexión)...")
        # getStatus suele requerir un ticket
        try:
            client.service.getStatus(ticket="1234567890123")
        except Fault as f:
            print(f"Fault recibido (esto es BUENO, significa que hubo comunicación): {f.message}")
            if "Unknown fault" in f.message:
                print("¡Bingo! Se reprodujo el 'Unknown fault occured'.")
            else:
                print("Conexión SOAP exitosa (SUNAT respondió con un error lógico).")
        except Exception as e:
            print(f"Error inesperado: {type(e).__name__}: {e}")
            
    except Exception as e:
        print(f"Error al inicializar cliente: {e}")

if __name__ == "__main__":
    test_connection()
