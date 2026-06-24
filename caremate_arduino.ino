// ============================================================
//   CareMate - Arduino UNO Main Sketch
//   Handles:
//     1. Motor Control  (L298N, 4 DC motors, differential drive)
//     2. Heartbeat Safety Stop (auto-stop if Pi goes silent)
//     3. Health Sensors (Pulse Sensor + DHT11 Temperature)
//
//   Serial Commands from Raspberry Pi:
//     'F' = Move Forward
//     'B' = Move Backward
//     'L' = Turn Left
//     'R' = Turn Right
//     'S' = Stop
//     'K' = Heartbeat Acknowledge (keep-alive)
//
//   Serial Output to Raspberry Pi (every 2 seconds):
//     {"hr":72,"temp":36.5,"status":"ok"}
//   Heartbeat to Pi (every 1 second):
//     'H'
// ============================================================

#include <DHT.h>

// ---- Motor Pins (L298N) ----
#define ENA 6   // PWM - Left motors speed
#define IN1 7   // Left motors direction
#define IN2 8
#define ENB 5   // PWM - Right motors speed
#define IN3 9   // Right motors direction
#define IN4 10

// ---- DHT11 Temperature Sensor ----
#define DHT_PIN  2
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

// ---- Pulse Sensor ----
#define PULSE_PIN A0

// ---- Speed Settings ----
#define SPEED_NORMAL  180   // 0-255 (PWM)
#define SPEED_TURN    160
#define SPEED_SLOW    120

// ---- Safety Heartbeat ----
unsigned long lastHeartbeatAck  = 0;
const unsigned long HEARTBEAT_TIMEOUT = 3000;  // ms - stop motors if no 'K' for 3s

// ---- Sensor Timing ----
unsigned long lastSensorSend    = 0;
const unsigned long SENSOR_INTERVAL = 2000;   // Send sensor data every 2s

unsigned long lastHeartbeatSend = 0;
const unsigned long HEARTBEAT_INTERVAL = 1000; // Send 'H' every 1s

// ---- BPM Calculation ----
int   pulseSensorVal = 0;
int   bpmBuffer[10];
int   bpmIndex       = 0;
int   currentBPM     = 0;
unsigned long lastBeatTime = 0;
bool  beatDetected   = false;
int   threshold      = 550;  // Tune this for your pulse sensor

// ============================================================
void setup() {
  Serial.begin(9600);

  // Motor pins
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  stopMotors();

  dht.begin();

  // Initialize BPM buffer
  for (int i = 0; i < 10; i++) bpmBuffer[i] = 70;

  lastHeartbeatAck = millis();  // Give grace period on start

  Serial.println("{\"status\":\"CareMate Arduino Ready\"}");
}

// ============================================================
void loop() {
  unsigned long now = millis();

  // ---- Read Serial Commands ----
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    handleCommand(cmd);
  }

  // ---- Heartbeat Safety Stop ----
  if (now - lastHeartbeatAck > HEARTBEAT_TIMEOUT) {
    stopMotors();  // Pi is not responding - SAFETY STOP
  }

  // ---- Send Heartbeat to Pi ----
  if (now - lastHeartbeatSend >= HEARTBEAT_INTERVAL) {
    Serial.print('H');
    lastHeartbeatSend = now;
  }

  // ---- Read Pulse Sensor ----
  readPulseSensor();

  // ---- Send Sensor Data to Pi ----
  if (now - lastSensorSend >= SENSOR_INTERVAL) {
    sendSensorData();
    lastSensorSend = now;
  }
}

// ============================================================
void handleCommand(char cmd) {
  switch (cmd) {
    case 'F': moveForward();  break;
    case 'B': moveBackward(); break;
    case 'L': turnLeft();     break;
    case 'R': turnRight();    break;
    case 'S': stopMotors();   break;
    case 'K':
      lastHeartbeatAck = millis();  // Acknowledge heartbeat
      break;
    default:
      break;
  }
}

// ============================================================
//   Motor Control Functions
// ============================================================
void moveForward() {
  analogWrite(ENA, SPEED_NORMAL);
  analogWrite(ENB, SPEED_NORMAL);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void moveBackward() {
  analogWrite(ENA, SPEED_NORMAL);
  analogWrite(ENB, SPEED_NORMAL);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void turnLeft() {
  // Right motors forward, left motors backward → spins left
  analogWrite(ENA, SPEED_TURN);
  analogWrite(ENB, SPEED_TURN);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void turnRight() {
  // Left motors forward, right motors backward → spins right
  analogWrite(ENA, SPEED_TURN);
  analogWrite(ENB, SPEED_TURN);
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void stopMotors() {
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
}

// ============================================================
//   Pulse Sensor BPM Calculation
// ============================================================
void readPulseSensor() {
  pulseSensorVal = analogRead(PULSE_PIN);
  unsigned long now = millis();

  if (pulseSensorVal > threshold && !beatDetected) {
    beatDetected = true;
    if (lastBeatTime > 0) {
      unsigned long interval = now - lastBeatTime;
      if (interval > 300 && interval < 2000) {  // Valid BPM range: 30-200
        int bpm = 60000 / interval;
        bpmBuffer[bpmIndex % 10] = bpm;
        bpmIndex++;
        // Calculate rolling average
        int sum = 0;
        for (int i = 0; i < 10; i++) sum += bpmBuffer[i];
        currentBPM = sum / 10;
      }
    }
    lastBeatTime = now;
  }

  if (pulseSensorVal < threshold - 50) {
    beatDetected = false;
  }
}

// ============================================================
//   Send Sensor Data as JSON
// ============================================================
void sendSensorData() {
  float temp = dht.readTemperature();   // Celsius
  float hum  = dht.readHumidity();

  if (isnan(temp)) temp = 0.0;
  if (isnan(hum))  hum  = 0.0;

  // Output JSON
  Serial.print("{\"hr\":");
  Serial.print(currentBPM);
  Serial.print(",\"temp\":");
  Serial.print(temp, 1);
  Serial.print(",\"hum\":");
  Serial.print(hum, 1);
  Serial.println(",\"status\":\"ok\"}");
}
