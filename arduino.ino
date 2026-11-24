#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
#include <ESP32Servo.h>

// -------- PINES --------
const int SERVO_PIN = 13;

const int LED_BLANCO1 = 25;
const int LED_BLANCO2 = 26;
const int LED_AMARILLO = 27;
const int LED_VERDE = 32;

// -------- OBJETOS --------
hd44780_I2Cexp lcd;
Servo barrera;

// -------- TIEMPOS --------
const unsigned long TIEMPO_MOVIMIENTO = 2000;
const unsigned long TIEMPO_ABIERTO = 3000;
const unsigned long TIEMPO_MENSAJE_DENEGADO = 3000;
const unsigned long INTERVALO_LED = 300;

// -------- ANGULOS --------
const int ANGULO_CERRADO = 0;
const int ANGULO_ABIERTO = 90;

// -------- ESTADOS --------
enum Estado {
  ESPERA,
  ABRIENDO,
  ACCESO,
  CERRANDO,
  DENEGADO
};

Estado estado = ESPERA;

// -------- VARIABLES --------
unsigned long tiempoEstado = 0;
unsigned long tiempoServo = 0;
unsigned long tiempoLED = 0;

int anguloActual = ANGULO_CERRADO;
int anguloInicio = ANGULO_CERRADO;
int anguloDestino = ANGULO_CERRADO;

bool ledsEncendidos = false;
String placaActual = "";

// -------- FUNCIONES --------

void apagarLEDs() {
  digitalWrite(LED_BLANCO1, LOW);
  digitalWrite(LED_BLANCO2, LOW);
  digitalWrite(LED_AMARILLO, LOW);
  digitalWrite(LED_VERDE, LOW);
}

void mostrarEspera() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("PARQUEADERO");
  lcd.setCursor(0, 1);
  lcd.print("ESPERANDO PLACA");

  apagarLEDs();
  digitalWrite(LED_BLANCO1, HIGH);
  digitalWrite(LED_BLANCO2, HIGH);
}

void iniciarMovimiento(int destino) {
  anguloInicio = anguloActual;
  anguloDestino = destino;
  tiempoServo = millis();
}

void actualizarServo() {
  unsigned long transcurrido = millis() - tiempoServo;

  if (transcurrido >= TIEMPO_MOVIMIENTO) {
    anguloActual = anguloDestino;
  } else {
    float progreso = (float)transcurrido / TIEMPO_MOVIMIENTO;
    anguloActual = anguloInicio + (anguloDestino - anguloInicio) * progreso;
  }

  barrera.write(anguloActual);
}

void iniciarCierre() {
  estado = CERRANDO;
  tiempoEstado = millis();

  iniciarMovimiento(ANGULO_CERRADO);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("BARRERA");
  lcd.setCursor(0, 1);
  lcd.print("CERRANDO...");

  apagarLEDs();
  ledsEncendidos = false;
  tiempoLED = millis();
}

// Procesa comandos enviados desde Python: "A:ABC123", "P:XYZ789" o "N:DEF456"
void procesarComandoCamara(String comando) {
  comando.trim();
  if (comando.length() == 0) return;

  char tipo = toupper(comando.charAt(0));
  placaActual = (comando.length() > 2 && comando.charAt(1) == ':') 
                ? comando.substring(2) 
                : "VEHICULO";

  if (tipo == 'A') {
    // PLACA AL DÍA -> LED VERDE + ABRE BARRERA
    estado = ABRIENDO;
    tiempoEstado = millis();
    iniciarMovimiento(ANGULO_ABIERTO);

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(placaActual);
    lcd.setCursor(0, 1);
    lcd.print("ACCESO PERMITIDO");

    apagarLEDs();
    digitalWrite(LED_VERDE, HIGH);
    Serial.println("OK: Abriendo para " + placaActual);

  } else if (tipo == 'P') {
    // PAGO PENDIENTE -> LED AMARILLO + NO ABRE
    estado = DENEGADO;
    tiempoEstado = millis();

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(placaActual);
    lcd.setCursor(0, 1);
    lcd.print("PAGO PENDIENTE");

    apagarLEDs();
    digitalWrite(LED_AMARILLO, HIGH);
    Serial.println("ALERTA: Pago pendiente - " + placaActual);

  } else if (tipo == 'N') {
    // NO REGISTRADA -> LED AMARILLO + BLANCO 1 + NO ABRE
    estado = DENEGADO;
    tiempoEstado = millis();

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(placaActual);
    lcd.setCursor(0, 1);
    lcd.print("NO REGISTRADA");

    apagarLEDs();
    digitalWrite(LED_AMARILLO, HIGH);
    digitalWrite(LED_BLANCO1, HIGH);
    Serial.println("DENEGADO: No registrada - " + placaActual);
  }
}

// -------- CONFIGURACION --------

void setup() {
  Serial.begin(115200);

  pinMode(LED_BLANCO1, OUTPUT);
  pinMode(LED_BLANCO2, OUTPUT);
  pinMode(LED_AMARILLO, OUTPUT);
  pinMode(LED_VERDE, OUTPUT);

  Wire.begin(21, 22);
  if (lcd.begin(16, 2)) {
    while (true) { delay(10); }
  }
  lcd.backlight();

  barrera.setPeriodHertz(50);
  barrera.attach(SERVO_PIN, 500, 2400);
  anguloActual = ANGULO_CERRADO;
  barrera.write(ANGULO_CERRADO);

  delay(500);
  mostrarEspera();
  Serial.println("SISTEMA LISTO. Esperando comandos de Python (A:PLACA, P:PLACA, N:PLACA)");
}

// -------- PROGRAMA PRINCIPAL --------

void loop() {
  unsigned long ahora = millis();

  // Escucha órdenes desde Python solo cuando el sistema está en ESPERA
  if (estado == ESPERA && Serial.available() > 0) {
    String mensaje = Serial.readStringUntil('\n');
    procesarComandoCamara(mensaje);
  }

  switch (estado) {
    case ESPERA:
      break;

    case ABRIENDO:
      actualizarServo();
      if (ahora - tiempoEstado >= TIEMPO_MOVIMIENTO) {
        anguloActual = ANGULO_ABIERTO;
        barrera.write(ANGULO_ABIERTO);

        estado = ACCESO;
        tiempoEstado = ahora;

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("PASE POR FAVOR");
        lcd.setCursor(0, 1);
        lcd.print(placaActual);
      }
      break;

    case ACCESO:
      if (ahora - tiempoEstado >= TIEMPO_ABIERTO) {
        iniciarCierre();
      }
      break;

    case CERRANDO:
      actualizarServo();

      if (ahora - tiempoLED >= INTERVALO_LED) {
        tiempoLED = ahora;
        ledsEncendidos = !ledsEncendidos;

        digitalWrite(LED_BLANCO1, ledsEncendidos);
        digitalWrite(LED_BLANCO2, ledsEncendidos);
        digitalWrite(LED_AMARILLO, ledsEncendidos);
        digitalWrite(LED_VERDE, ledsEncendidos);
      }

      if (ahora - tiempoEstado >= TIEMPO_MOVIMIENTO) {
        anguloActual = ANGULO_CERRADO;
        barrera.write(ANGULO_CERRADO);

        estado = ESPERA;
        mostrarEspera();
      }
      break;

    case DENEGADO:
      if (ahora - tiempoEstado >= TIEMPO_MENSAJE_DENEGADO) {
        estado = ESPERA;
        mostrarEspera();
      }
      break;
  }
}