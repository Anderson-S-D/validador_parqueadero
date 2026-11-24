# ParkControl: Sistema Validador de Parqueadero Inteligente (ESP32 + Visión Artificial + Portal Web)

Sistema integral de control de acceso vehicular desarrollado para **Arquitectura de Computadores**. Combina un sistema embebido basado en **ESP32**, reconocimiento óptico de caracteres (**OpenCV + EasyOCR**) mediante cámara IP/USB y un **Portal Web Administrativo (FastAPI)** para la gestión de vehículos, liquidación de tarifas, control de talanquera y telemetría en tiempo real.

---

## Tabla de Contenidos

1. [Descripción General](#descripción-general)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Hardware, Pinout y Máquina de Estados](#hardware-pinout-y-máquina-de-estados)
4. [Estructura del Proyecto](#estructura-del-proyecto)
5. [Módulos del Portal Web](#módulos-del-portal-web)
6. [Requisitos Previos e Instalación](#requisitos-previos-e-instalación)
7. [Configuración y Ejecución](#configuración-y-ejecución)
8. [Protocolo Serial y API REST](#protocolo-serial-y-api-rest)
9. [Solución de Problemas (Troubleshooting)](#solución-de-problemas-troubleshooting)

---

## Descripción General

Cuando un vehículo se aproxima a la barrera de acceso:
1. La cámara captura el flujo de video en tiempo real y el motor **EasyOCR** extrae el texto de la placa validando el formato vehicular colombiano (`^[A-Z]{3}[0-9]{2}[0-9A-Z]$`).
2. El backend consulta el estado de la placa en la base de datos JSON (`A`: Pago validado, `P`: Pendiente por pagar, `N`: Sin registro de ingreso).
3. El servidor envía una trama por puerto serial UART a la **ESP32** (`<ESTADO>:<PLACA>\n`).
4. La **ESP32** ejecuta su máquina de estados finitos accionando el servomotor de la talanquera, los LEDs indicadores y los mensajes en la pantalla LCD.
5. Toda la operación queda registrada en la bitácora del portal web, permitiendo además cobros en caja, altas/bajas de vehículos y apertura manual remota.

---

## Arquitectura del Sistema

```text
+-------------------+       MJPEG / RTSP        +---------------------------------------+
|  Cámara IP / USB  | ------------------------> |          Backend Python (FastAPI)     |
+-------------------+                           |                                       |
                                                |  +-------------+   +---------------+  |
+-------------------+     HTTP REST / MJPEG     |  | OpenCV+OCR  |   | ParkingService|  |
|   Portal Web UI   | <-----------------------> |  +------+------+   +-------+-------+  |
| (HTML / CSS / JS) |                           |         |                  |          |
+-------------------+                           |         v                  v          |
                                                |  +-------------+   +---------------+  |
                                                |  |HardwareBridge|   | parking_db.json| |
                                                |  +------+------+   |base_placas.json| |
                                                +---------|----------+---------------+--+
                                                          | UART Serial (115200 baudios)
                                                          v
                                                +---------------------------------------+
                                                |             ESP32 DevKit              |
                                                |  - LCD 16x2 I2C (SDA: 21, SCL: 22)    |
                                                |  - Servomotor Barrera (GPIO 13)       |
                                                |  - 4x LEDs Estado (GPIO 25,26,27,32)  |
                                                +---------------------------------------+
```

---

## Hardware, Pinout y Máquina de Estados

### Lista de Materiales (BOM)
* **1x** Microcontrolador ESP32 (30 o 38 pines).
* **1x** Pantalla LCD $16 \times 2$ con módulo adaptador I2C (`PCF8574`).
* **1x** Servomotor (`SG90` o `MG995` para talanquera).
* **4x** LEDs difusos de $5\text{ mm}$ (2 Blancos, 1 Amarillo, 1 Verde).
* **4x** Resistencias limitadoras de **$220\ \Omega$** ($1/4\text{ W}$).
* **1x** Fuente externa regulada de $5\text{ V}$ DC (recomendada para alimentar el servomotor con tierra común `GND` hacia la ESP32).

> **Advertencia de Diseño Electrónico:** Para los LEDs conectados a los pines GPIO de $3.3\text{ V}$ de la ESP32 deben emplearse resistencias de **$220\ \Omega$** (código de colores: rojo-rojo-marrón), lo cual proporciona una corriente segura de $\approx 6\text{ mA}$ a $7\text{ mA}$. Si se usan resistencias de $220\text{ k}\Omega$, la corriente cae al orden de microamperios y los LEDs no iluminarán visiblemente.

### Tabla de Conexiones (Pinout ESP32)

| Componente | Pin ESP32 | Protocolo / Tipo | Función |
| :--- | :--- | :--- | :--- |
| **Servomotor (Señal)** | `GPIO 13` | PWM ($50\text{ Hz}$) | Control angular de barrera ($0^\circ$ a $90^\circ$) |
| **LCD I2C (`SDA`)** | `GPIO 21` | I2C Data | Bus de datos de pantalla $16 \times 2$ |
| **LCD I2C (`SCL`)** | `GPIO 22` | I2C Clock | Reloj de sincronización I2C |
| **LED Blanco 1** | `GPIO 25` | Salida Digital | Modo espera / Apoyo alerta no registrada |
| **LED Blanco 2** | `GPIO 26` | Salida Digital | Modo espera / Parpadeo cierre |
| **LED Amarillo** | `GPIO 27` | Salida Digital | Alerta pago pendiente (`P`) o no registrada (`N`) |
| **LED Verde** | `GPIO 32` | Salida Digital | Acceso permitido (`A`) / Apertura barrera |

### Lógica de Estados de la ESP32

| Estado | Disparador | Comportamiento LCD ($16 \times 2$) | LEDs Activos | Posición Servo |
| :--- | :--- | :--- | :--- | :--- |
| **`ESPERA`** | Inicio o fin de ciclo | `PARQUEADERO` / `ESPERANDO PLACA` | Blanco 1 + Blanco 2 | Cerrado ($0^\circ$) |
| **`ABRIENDO`** | Trama `A:<PLACA>` | `<PLACA>` / `ACCESO PERMITIDO` | Verde | Interpolando $0^\circ \rightarrow 90^\circ$ ($2\text{ s}$) |
| **`ACCESO`** | Fin apertura | `PASE POR FAVOR` / `<PLACA>` | Verde | Abierto ($90^\circ$ por $3\text{ s}$) |
| **`CERRANDO`** | Fin tiempo acceso | `BARRERA` / `CERRANDO...` | Todos parpadean ($300\text{ ms}$) | Interpolando $90^\circ \rightarrow 0^\circ$ ($2\text{ s}$) |
| **`DENEGADO` (`P`)** | Trama `P:<PLACA>` | `<PLACA>` / `PAGO PENDIENTE` | Amarillo ($3\text{ s}$) | Cerrado ($0^\circ$) |
| **`DENEGADO` (`N`)** | Trama `N:<PLACA>` | `<PLACA>` / `NO REGISTRADA` | Amarillo + Blanco 1 ($3\text{ s}$) | Cerrado ($0^\circ$) |

---

## Estructura del Proyecto

```text
validador_parqueadero/
├── main.py                  # Servidor FastAPI, rutas REST y streaming MJPEG
├── requirements.txt         # Dependencias de Python
├── README.md                # Documentación del proyecto
├── base_placas.json         # Archivo sincronizado (formato clave-valor original)
├── parking_db.json          # Base de datos completa (vehículos, tarifas y bitácora)
├── firmware/
│   └── validador_esp32.ino  # Código fuente C++ para la ESP32
├── app/
│   ├── __init__.py
│   ├── schemas.py           # Modelos de validación de datos (Pydantic)
│   ├── repository.py        # Persistencia atómica thread-safe en JSON
│   ├── hardware.py          # Puente UART Serial con ESP32 + Worker OpenCV/EasyOCR
│   └── services.py          # Lógica de negocio, tarifas y métricas
└── static/
    ├── index.html           # Interfaz web administrativa
    ├── styles.css           # Hojas de estilo responsivas
    └── app.js               # Cliente JavaScript y actualización en tiempo real
```

---

## Módulos del Portal Web

1. **Monitor en Vivo:** Visualización en tiempo real del flujo de video procesado, gemelo digital del LCD $16 \times 2$, estado de los 4 LEDs, ángulo de la talanquera y simulador manual de lectura de placas.
2. **Placas y Estados (CRUD):** Registro de ingresos (`P`), validación de mensualidades (`A`), consulta y eliminación de vehículos con sincronización automática sobre `base_placas.json` y `parking_db.json`.
3. **Caja y Liquidación:** Cálculo automático de estadía en minutos según tipo de vehículo (`CARRO` o `MOTO`), aplicación de minutos de gracia, recaudo y apertura automática de barrera al confirmar el pago.
4. **Bitácora de Eventos:** Historial cronológico de lecturas OCR, rechazos, pagos liquidados y aperturas manuales con trazabilidad de transmisión serial (`TX`).
5. **Configuración:** Ajuste dinámico de tarifas por minuto, tiempo de gracia, puerto COM de la ESP32, URL de cámara IP y tiempo de *cooldown* del OCR.

---

## Requisitos Previos e Instalación

### 1. Firmware en ESP32 (Arduino IDE)
Instalar las siguientes librerías desde el **Gestor de Librerías** de Arduino IDE:
* `hd44780` (por Bill Perry)
* `ESP32Servo` (por Kevin Harrington / John K. Bennett)

Seleccionar la placa **ESP32 Dev Module**, velocidad de carga `115200` y cargar el archivo `firmware/validador_esp32.ino`.

### 2. Backend y Portal Web (Python 3.10+)

```bash
# 1. Clonar o ubicarse en la carpeta del proyecto
cd validador_parqueadero

# 2. Crear y activar entorno virtual
py -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux/macOS:
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

> **Nota:** La primera vez que se inicie el sistema, `EasyOCR` descargará automáticamente los pesos del modelo de reconocimiento de texto en inglés ($\approx 100\text{ MB}$).

---

## Configuración y Ejecución

1. **Verificar Puerto Serial:** Asegúrate de cerrar el *Monitor Serial* de Arduino IDE para liberar el puerto COM asignado a la ESP32 (por defecto `COM7`).
2. **Iniciar el servidor unificado:**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

3. **Acceder al Portal Web:** Abre tu navegador en `http://localhost:8000`.
4. **Ajustar parámetros:** Si tu cámara IP utiliza una URL RTSP/HTTP (ej. `http://192.168.1.50:8080/video`) o tu ESP32 está en otro puerto (`COM3`, `/dev/ttyUSB0`), modifícalo directamente desde la pestaña **Configuración** del portal sin editar código fuente.

> **Modo Simulación:** Si ejecutas el servidor sin la ESP32 conectada o sin cámara activa, el sistema entra automáticamente en *Modo Simulación*, permitiendo probar toda la lógica web, el cobro en caja y la actualización de los archivos `.json` sin errores de ejecución.

---

## Protocolo Serial y API REST

### Protocolo UART (`115200` baudios, terminado en `\n`)
* `A:<PLACA>\n` $\rightarrow$ Autoriza acceso y abre la barrera.
* `P:<PLACA>\n` $\rightarrow$ Deniega acceso por pago pendiente.
* `N:<PLACA>\n` $\rightarrow$ Deniega acceso por placa no registrada.

### Endpoints Principales de la API

| Método | Ruta | Descripción |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard` | Retorna KPIs, estado de conexión serial/cámara, última detección y logs recientes. |
| `GET` | `/api/vehiculos` | Lista todos los vehículos registrados junto con su liquidación acumulada. |
| `POST` | `/api/vehiculos` | Registra un nuevo vehículo o ingreso en `parking_db.json` y `base_placas.json`. |
| `PUT` | `/api/vehiculos/{placa}` | Actualiza propietario, tipo o estado (`A`, `P`, `N`) de una placa. |
| `DELETE` | `/api/vehiculos/{placa}` | Elimina una placa de la base de datos. |
| `GET` | `/api/caja/{placa}` | Calcula minutos transcurridos y valor a pagar según tarifa vigente. |
| `POST` | `/api/caja/pagar` | Registra el pago, pasa la placa a estado `A` y envía comando de apertura. |
| `POST` | `/api/hardware/abrir-manual` | Envía `A:MANUAL\n` para apertura de emergencia de la barrera. |
| `POST` | `/api/hardware/simular` | Simula la detección OCR de una placa específica. |
| `GET` | `/api/video_feed` | Stream de video MJPEG en vivo con superposición de estado OCR. |

---

## Solución de Problemas (Troubleshooting)

* **Error `Access is denied` o `PermissionError` en el puerto COM:**
  El Monitor Serial de Arduino IDE o el script standalone anterior sigue abierto usando el puerto. Ciérralo y presiona **Reconectar COM** en la barra lateral del portal.
* **La ESP32 se reinicia cuando se mueve el servomotor:**
  El pico de corriente del servomotor excede la capacidad del regulador interno de $3.3\text{ V}$ o del puerto USB. Alimenta el servomotor con una fuente externa de $5\text{ V}$ y une el cable `GND` de la fuente con el `GND` de la ESP32.
* **La pantalla LCD enciende pero no muestra caracteres:**
  Ajusta el potenciómetro azul en la parte posterior del módulo adaptador I2C para calibrar el contraste y verifica que `SDA` esté en `GPIO 21` y `SCL` en `GPIO 22`.
* **El portal responde lento al inicio:**
  `EasyOCR` está cargando el modelo neuronal en memoria CPU (`gpu=False`). Una vez inicializado, procesa 1 de cada 10 fotogramas manteniendo fluidez en el streaming MJPEG.

---

## Licencia y Uso Académico

Proyecto desarrollado con fines académicos y de ingeniería para la asignatura de **Arquitectura de Computadores**. Libre para modificación, integración con sensores adicionales (ultrasonido/infrarrojo) y despliegue en entornos locales.