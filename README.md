# CareMate - AI-Powered Elderly Care Companion Robot

**Group 15 | MES Kuttippuram | Guided by: Mr. Abin C Jose**

---

## Project Overview

CareMate is an AI-powered elderly care companion robot that provides:
- 👤 Vision-based **person detection and following**
- ⚠️ Vision-based **fall detection** with real-time alerts
- ❤️ **Vital signs monitoring** (heart rate, temperature)
- 🎤 **Bilingual voice assistant** (Malayalam & English)
- 📊 **Live caregiver dashboard** (web-based)
- 📱 **Telegram alerts** with photo evidence

**Hardware:** Raspberry Pi + Arduino UNO + L298N Motor Driver + USB Webcam + 4 DC Motors

---

## Folder Structure

```
caremate/
├── config.py                          ← ⭐ EDIT THIS FIRST
├── requirements.txt
├── README.md
│
├── module_01_person_following/        ← Vision + Motor Control
│   ├── person_following.py
│   └── test_motors.py
│
├── module_02_fall_detection/          ← Pose Estimation + Alerts
│   └── fall_detection.py
│
├── module_03_health_monitoring/       ← Heart Rate + Temperature
│   ├── health_monitor.py
│   └── arduino_health/
│       └── arduino_health.ino
│
├── module_04_voice_assistant/         ← Malayalam + English Voice
│   └── voice_assistant.py
│
├── module_05_dashboard_alerts/        ← Flask Web Dashboard
│   ├── app.py
│   ├── telegram_bot.py
│   └── templates/index.html
│
├── arduino_main/
│   └── caremate_arduino.ino           ← ⭐ FLASH THIS TO ARDUINO
│
└── full_system/                       ← ⭐ FULL INTEGRATED SYSTEM
    ├── main.py
    └── shared_state.py
```

---

## Setup Instructions

### Step 1 – Configure (IMPORTANT)

Edit `config.py`:
```python
TELEGRAM_BOT_TOKEN = "your_bot_token"    # From @BotFather on Telegram
TELEGRAM_CHAT_ID   = "7343807502"         # Your chat ID
SERIAL_PORT        = "/dev/ttyACM0"       # Check with: ls /dev/tty*
GROQ_API_KEY       = "your_groq_key"      # From console.groq.com (free)
```

### Step 2 – Flash Arduino

1. Open `arduino_main/caremate_arduino.ino` in Arduino IDE
2. Install library: **DHT sensor library** by Adafruit
3. Select Board: **Arduino UNO**
4. Upload to Arduino

### Step 3 – Install Python Dependencies

```bash
pip install -r requirements.txt --break-system-packages
```

Also install system packages:
```bash
sudo apt install espeak portaudio19-dev mpg321
```

### Step 4 – Download YOLO Models

```bash
python3 -c "
from ultralytics import YOLO
YOLO('yolov8n.pt')
YOLO('yolov8n-pose.pt')
print('Models downloaded.')
"
```

### Step 5 – Test Motors First!

```bash
cd module_01_person_following
python test_motors.py
```
This tests Forward / Backward / Left / Right one by one.
If any motor spins the wrong way, swap its wire pair.

### Step 6 – Run the Full System

```bash
cd full_system
python main.py
```

Access dashboard at: `http://<raspberry-pi-ip>:5000`

---

## Running Individual Modules (for demo / testing)

| Module | Command |
|--------|---------|
| Person Following only | `cd module_01_person_following && python person_following.py` |
| Fall Detection only   | `cd module_02_fall_detection && python fall_detection.py` |
| Health Monitor only   | `cd module_03_health_monitoring && python health_monitor.py` |
| Voice Assistant only  | `cd module_04_voice_assistant && python voice_assistant.py` |
| Dashboard only        | `cd module_05_dashboard_alerts && python app.py` |
| Test Telegram         | `cd module_05_dashboard_alerts && python telegram_bot.py` |

---

## Hardware Wiring

### L298N Motor Driver → Arduino UNO

| L298N Pin | Arduino Pin | Purpose              |
|-----------|------------|----------------------|
| ENA       | D6 (PWM)   | Left motor speed     |
| IN1       | D7         | Left motor direction |
| IN2       | D8         | Left motor direction |
| ENB       | D5 (PWM)   | Right motor speed    |
| IN3       | D9         | Right motor direction|
| IN4       | D10        | Right motor direction|
| VCC       | +12V       | Motor power          |
| GND       | GND        | Common ground        |
| 5V out    | 5V Arduino | (optional)           |

### DHT11 Temperature Sensor → Arduino

| DHT11 | Arduino |
|-------|---------|
| VCC   | 5V      |
| GND   | GND     |
| DATA  | D2      |

### Pulse Sensor → Arduino

| Pulse Sensor | Arduino |
|-------------|---------|
| VCC          | 5V      |
| GND          | GND     |
| Signal       | A0      |

### Raspberry Pi → Arduino

- USB cable (USB-A to USB-B)
- Serial port: `/dev/ttyACM0` (default)

---

## Serial Protocol (Pi ↔ Arduino)

| Direction     | Data          | Meaning               |
|--------------|---------------|-----------------------|
| Pi → Arduino  | `F`           | Move Forward          |
| Pi → Arduino  | `B`           | Move Backward         |
| Pi → Arduino  | `L`           | Turn Left             |
| Pi → Arduino  | `R`           | Turn Right            |
| Pi → Arduino  | `S`           | Stop                  |
| Pi → Arduino  | `K`           | Heartbeat acknowledge |
| Arduino → Pi  | `H`           | Heartbeat (every 1s)  |
| Arduino → Pi  | `{"hr":72,...}` | Sensor data (every 2s) |

**Safety Feature:** If Arduino does not receive `K` for 3 seconds, it stops all motors automatically.

---

## Team

| Name             | Role                        |
|------------------|-----------------------------|
| Abhishekh P      | Vision & System Lead        |
| Ranila CP        | Voice Assistant Developer   |
| Reeha Al Samar   | Dashboard & UI Developer    |
| Hiba Shamsudheen | IoT & Documentation Lead    |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Serial port not found | Run `ls /dev/tty*`, update `SERIAL_PORT` in config.py |
| Camera not detected   | Try `CAMERA_INDEX = 1` in config.py |
| YOLO model not found  | Run the model download command in Step 4 |
| Telegram not sending  | Check bot token and chat ID in config.py |
| Motors not moving     | Run `test_motors.py` first; check wiring |
| Arduino keeps stopping| Ensure `K` heartbeat is being sent; check serial |
| Qt display error      | Use `opencv-python-headless` instead of `opencv-python` |
