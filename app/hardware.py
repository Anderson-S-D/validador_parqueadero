import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

import cv2
import numpy as np
import serial

try:
    import easyocr
except ImportError:
    easyocr = None


class HardwareBridge:
    def __init__(self, repo: Any):
        self.repo = repo
        self._serial_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self.esp32: Optional[serial.Serial] = None
        self.serial_conectado = False
        self.ultimo_mensaje_esp32 = "Sin telemetría"
        self.camara_activa = False
        self.ultimo_frame_jpg: Optional[bytes] = None
        self.ultima_deteccion: Dict[str, Any] = {
            "placa": "---",
            "estado": "ESPERA",
            "descripcion": "Esperando vehículo",
            "timestamp": None,
        }
        self._running = False
        self._patron_placa = re.compile(r"^[A-Z]{3}[0-9]{2}[0-9A-Z]$")
        self._reader = None

    def iniciar(self) -> None:
        if self._running:
            return
        self._running = True
        self.conectar_serial()
        threading.Thread(target=self._bucle_lectura_serial, daemon=True).start()
        threading.Thread(target=self._bucle_vision, daemon=True).start()

    def detener(self) -> None:
        self._running = False
        with self._serial_lock:
            if self.esp32 and self.esp32.is_open:
                self.esp32.close()

    def conectar_serial(self) -> bool:
        config = self.repo.obtener_todo()["config"]
        puerto = config.get("puerto_esp32", "COM7")
        with self._serial_lock:
            try:
                if self.esp32 and self.esp32.is_open:
                    self.esp32.close()
                self.esp32 = serial.Serial(puerto, 115200, timeout=0.2)
                time.sleep(1.5)
                self.serial_conectado = True
                self.ultimo_mensaje_esp32 = f"Conectado en {puerto}"
                return True
            except Exception as e:
                self.serial_conectado = False
                self.ultimo_mensaje_esp32 = f"Modo Simulación ({e})"
                return False

    def enviar_comando_esp32(self, estado: str, placa: str, origen: str = "CAMARA") -> Dict[str, Any]:
        comando = f"{estado}:{placa}\n"
        enviado_fisico = False

        with self._serial_lock:
            if self.esp32 and self.esp32.is_open:
                try:
                    self.esp32.write(comando.encode("utf-8"))
                    enviado_fisico = True
                except Exception as e:
                    self.serial_conectado = False
                    self.ultimo_mensaje_esp32 = f"Error TX: {e}"

        descripciones = {
            "A": "ACCESO PERMITIDO - Barrera abierta (LED Verde)",
            "P": "PAGO PENDIENTE - Barrera cerrada (LED Amarillo)",
            "N": "NO REGISTRADA - Barrera cerrada (LED Amarillo + Blanco 1)",
        }

        ahora_iso = datetime.now().isoformat()
        self.ultima_deteccion = {
            "placa": placa,
            "estado": estado,
            "descripcion": descripciones.get(estado, "Desconocido"),
            "timestamp": ahora_iso,
            "origen": origen,
            "enviado_fisico": enviado_fisico,
        }

        self.repo.registrar_evento({
            "timestamp": ahora_iso,
            "placa": placa,
            "estado": estado,
            "origen": origen,
            "detalle": self.ultima_deteccion["descripcion"],
            "hardware_tx": enviado_fisico,
        })

        return self.ultima_deteccion

    def _bucle_lectura_serial(self) -> None:
        while self._running:
            linea = ""
            with self._serial_lock:
                if self.esp32 and self.esp32.is_open and self.esp32.in_waiting > 0:
                    try:
                        linea = self.esp32.readline().decode("utf-8", errors="ignore").strip()
                    except Exception:
                        self.serial_conectado = False
            if linea:
                self.ultimo_mensaje_esp32 = linea
            time.sleep(0.1)

    def _generar_frame_placeholder(self, mensaje: str) -> bytes:
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img[:] = (24, 28, 36)
        cv2.putText(img, "CAMARA IP NO DISPONIBLE", (120, 165), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
        cv2.putText(img, mensaje[:55], (90, 205), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 190, 205), 1)
        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()

    def _bucle_vision(self) -> None:
        if easyocr is not None:
            try:
                self._reader = easyocr.Reader(["en"], gpu=False)
            except Exception:
                self._reader = None

        ultima_placa = ""
        ultimo_tiempo = 0.0
        contador = 0
        cap = None
        url_actual = None

        while self._running:
            config = self.repo.obtener_todo()["config"]
            url_cfg = str(config.get("url_camara", "0")).strip()
            fuente = int(url_cfg) if url_cfg.isdigit() else url_cfg
            cooldown = int(config.get("cooldown_segundos", 8))

            if cap is None or url_actual != fuente:
                if cap is not None:
                    cap.release()
                cap = cv2.VideoCapture(fuente)
                url_actual = fuente

            if not cap.isOpened():
                self.camara_activa = False
                with self._frame_lock:
                    self.ultimo_frame_jpg = self._generar_frame_placeholder(f"Fuente: {url_cfg}")
                time.sleep(2.0)
                cap.release()
                cap = None
                continue

            ret, frame = cap.read()
            if not ret:
                self.camara_activa = False
                time.sleep(0.3)
                continue

            self.camara_activa = True
            contador += 1

            if self._reader is not None and contador % 10 == 0:
                ahora = time.time()
                gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                resultados = self._reader.readtext(gris, detail=0)

                for texto in resultados:
                    limpio = re.sub(r"[^A-Z0-9]", "", texto.upper())
                    if self._patron_placa.match(limpio):
                        if limpio != ultima_placa or (ahora - ultimo_tiempo) > cooldown:
                            vehiculo = self.repo.obtener_vehiculo(limpio)
                            estado = vehiculo["estado"] if vehiculo else "N"
                            self.enviar_comando_esp32(estado, limpio, origen="CAMARA_OCR")
                            ultima_placa = limpio
                            ultimo_tiempo = ahora
                        break

            estado_actual = self.ultima_deteccion["estado"]
            color = (0, 255, 0) if estado_actual == "A" else (0, 220, 255) if estado_actual == "P" else (80, 80, 255)
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 42), (15, 18, 25), -1)
            cv2.putText(
                frame,
                f"{self.ultima_deteccion['placa']} - {estado_actual}",
                (15, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                color,
                2,
            )

            _, buffer = cv2.imencode(".jpg", frame)
            with self._frame_lock:
                self.ultimo_frame_jpg = buffer.tobytes()

            time.sleep(0.03)

        if cap is not None:
            cap.release()

    def obtener_frame(self) -> bytes:
        with self._frame_lock:
            if self.ultimo_frame_jpg is not None:
                return self.ultimo_frame_jpg
        return self._generar_frame_placeholder("Iniciando stream...")