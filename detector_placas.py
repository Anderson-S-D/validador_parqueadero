import cv2
import easyocr
import serial
import time
import re
import json
import os

# ================= CONFIGURACIÓN =================
# Cambia esta URL por la IP/stream de tu cámara Wi-Fi
URL_CAMARA = 0 
PUERTO_ESP32 = "COM7"    # Verifica tu puerto COM en el Administrador de Dispositivos o Arduino IDE
BAUDIOS = 115200
COOLDOWN_SEGUNDOS = 8    # Segundos de espera antes de volver a enviar la misma placa
# =================================================

def cargar_base_placas():
    ruta = os.path.join(os.path.dirname(__file__), "base_placas.json")
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[AVISO] No se pudo leer base_placas.json ({e}). Usando base vacía.")
        return {}

# 1. Conectar con la ESP32 por USB
try:
    esp32 = serial.Serial(PUERTO_ESP32, BAUDIOS, timeout=1)
    time.sleep(2)
    print(f"[OK] Conectado a ESP32 en {PUERTO_ESP32}")
except Exception as e:
    print(f"[ERROR] No se pudo abrir {PUERTO_ESP32}. Cierra Arduino IDE si está abierto. Detalle: {e}")
    exit()

# 2. Inicializar OCR (la primera vez descarga los pesos del modelo, tarda ~1 min)
print("[INFO] Cargando motor OCR...")
reader = easyocr.Reader(['en'], gpu=False)

# 3. Conectar al flujo de video de la cámara IP
cap = cv2.VideoCapture(URL_CAMARA)
if not cap.isOpened():
    print(f"[ERROR] No se pudo abrir el video en {URL_CAMARA}")
    esp32.close()
    exit()

print("[OK] Sistema iniciado. Presiona 'q' en la ventana de cámara para cerrar.")

ultima_deteccion_tiempo = 0
ultima_placa_enviada = ""
texto_estado_pantalla = "ESPERANDO PLACA..."
color_estado = (255, 255, 255)
contador_frames = 0

# Formato placa Colombia: 3 letras + 3 números (carro) o 3 letras + 2 números + 1 letra (moto)
patron_placa = re.compile(r'^[A-Z]{3}[0-9]{2}[0-9A-Z]$')

while True:
    ret, frame = cap.read()
    if not ret:
        print("[AVISO] Reintentando conexión con la cámara...")
        time.sleep(0.5)
        continue

    contador_frames += 1

    # Analizar 1 de cada 10 fotogramas para fluidez
    if contador_frames % 10 == 0:
        ahora = time.time()
        gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        resultados = reader.readtext(gris, detail=0)

        for texto in resultados:
            limpio = re.sub(r'[^A-Z0-9]', '', texto.upper())

            if patron_placa.match(limpio):
                if limpio != ultima_placa_enviada or (ahora - ultima_deteccion_tiempo) > COOLDOWN_SEGUNDOS:
                    base_datos = cargar_base_placas()
                    estado = base_datos.get(limpio, "N")
                    comando = f"{estado}:{limpio}\n"

                    esp32.write(comando.encode('utf-8'))
                    print(f"[ENVIADO] -> {comando.strip()}")

                    if estado == "A":
                        texto_estado_pantalla = f"{limpio} - ACCESO PERMITIDO"
                        color_estado = (0, 255, 0)     # Verde
                    elif estado == "P":
                        texto_estado_pantalla = f"{limpio} - PAGO PENDIENTE"
                        color_estado = (0, 255, 255)   # Amarillo
                    else:
                        texto_estado_pantalla = f"{limpio} - NO REGISTRADA"
                        color_estado = (0, 0, 255)     # Rojo

                    ultima_placa_enviada = limpio
                    ultima_deteccion_tiempo = ahora
                break

    # Dibujar barra superior informativa en la vista previa
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 45), (0, 0, 0), -1)
    cv2.putText(frame, texto_estado_pantalla, (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_estado, 2)

    cv2.imshow("Control Acceso Parqueadero", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
esp32.close()
cv2.destroyAllWindows()