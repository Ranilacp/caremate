"""
============================================================
  CareMate - Module 03: Health Monitoring
  ============================================================
  Reads heartbeat (BPM) and temperature data sent by Arduino
  as JSON over serial port.

  Expected Arduino output format (every 2 seconds):
    {"hr":72,"temp":36.5,"hum":60.0,"status":"ok"}

  Features:
    - Real-time health data parsing
    - Abnormal value detection (alerts via Telegram + espeak)
    - Data logging to file
    - Thread-safe shared state for dashboard access

  Run standalone:
    python health_monitor.py
============================================================
"""

import serial
import json
import time
import sys
import os
import logging
import threading
import subprocess
import requests
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [HEALTH] %(message)s')
log = logging.getLogger(__name__)


class HealthMonitor:
    """
    Reads health sensor data from Arduino and monitors for abnormal values.
    Thread-safe: can be queried from other threads (e.g., dashboard).
    """

    def __init__(self, serial_conn=None):
        """
        Args:
            serial_conn: Shared serial.Serial object (pass from full_system to avoid
                         opening the same port twice). If None, opens its own connection.
        """
        self._lock = threading.Lock()

        # Latest readings (thread-safe access via get_latest())
        self._latest = {
            "hr":     0,
            "temp":   0.0,
            "hum":    0.0,
            "status": "initializing",
            "timestamp": None,
            "hr_alert":   False,
            "temp_alert": False,
        }

        self.ser         = serial_conn
        self._owns_serial = serial_conn is None   # True if we opened the connection

        self.running     = False
        self._last_alert_time = 0
        self.ALERT_COOLDOWN   = 60  # seconds between health alerts

        # Ensure log directory exists
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self._log_path = os.path.join(config.LOG_DIR, "health_log.csv")
        self._init_log_file()

    # ----------------------------------------------------------
    def _init_log_file(self):
        if not os.path.exists(self._log_path):
            with open(self._log_path, 'w') as f:
                f.write("timestamp,hr,temp,humidity,hr_alert,temp_alert\n")

    # ----------------------------------------------------------
    def start(self):
        """Open serial (if needed) and begin reading loop."""
        if self._owns_serial:
            log.info(f"Connecting to Arduino on {config.SERIAL_PORT}...")
            try:
                self.ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE,
                                         timeout=config.SERIAL_TIMEOUT)
                time.sleep(2)
                log.info("Serial connected for health monitoring.")
            except serial.SerialException as e:
                log.error(f"Serial error: {e}")
                log.info("Running in simulation mode.")
                self.ser = None

        self.running = True
        log.info("Health monitoring started.")
        self._loop()

    # ----------------------------------------------------------
    def _loop(self):
        """Main loop: read serial, parse JSON, check thresholds."""
        try:
            while self.running:
                if self.ser is None:
                    # Simulation mode: generate fake data
                    self._process_reading(72, 36.5, 60.0)
                    time.sleep(2)
                    continue

                try:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                except serial.SerialException:
                    log.warning("Serial read error. Retrying...")
                    time.sleep(1)
                    continue

                # Skip non-JSON lines (heartbeat 'H', commands echo, etc.)
                if not line.startswith('{'):
                    if line == 'H':
                        # Arduino heartbeat - just acknowledge
                        if self.ser and self.ser.is_open:
                            self.ser.write(b'K')
                    continue

                try:
                    data = json.loads(line)
                    hr   = int(data.get('hr',   0))
                    temp = float(data.get('temp', 0.0))
                    hum  = float(data.get('hum',  0.0))
                    self._process_reading(hr, temp, hum)
                except (json.JSONDecodeError, ValueError):
                    pass    # Ignore malformed lines

        except KeyboardInterrupt:
            log.info("Interrupted.")
        finally:
            if self._owns_serial and self.ser:
                self.ser.close()
            log.info("Health monitoring stopped.")

    # ----------------------------------------------------------
    def _process_reading(self, hr, temp, hum):
        """Validate reading, update shared state, log, alert if needed."""
        timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hr_alert      = (hr < config.HR_LOW or hr > config.HR_HIGH) and hr > 0
        temp_alert    = (temp < config.TEMP_LOW or temp > config.TEMP_HIGH) and temp > 0

        log.info(f"HR={hr} BPM  Temp={temp}°C  Hum={hum}%  "
                 f"{'⚠ HR ALERT' if hr_alert else ''}"
                 f"{'⚠ TEMP ALERT' if temp_alert else ''}")

        # Update shared state
        with self._lock:
            self._latest.update({
                "hr":         hr,
                "temp":       temp,
                "hum":        hum,
                "status":     "ok",
                "timestamp":  timestamp,
                "hr_alert":   hr_alert,
                "temp_alert": temp_alert,
            })

        # Log to CSV
        with open(self._log_path, 'a') as f:
            f.write(f"{timestamp},{hr},{temp},{hum},{hr_alert},{temp_alert}\n")

        # Send alert if threshold exceeded (with cooldown)
        if (hr_alert or temp_alert):
            now = time.time()
            if now - self._last_alert_time > self.ALERT_COOLDOWN:
                self._last_alert_time = now
                self._send_health_alert(hr, temp, hr_alert, temp_alert, timestamp)

    # ----------------------------------------------------------
    def _send_health_alert(self, hr, temp, hr_alert, temp_alert, timestamp):
        """Send health alert via Telegram and espeak."""
        msg_parts = []
        if hr_alert:
            msg_parts.append(f"Heart rate abnormal: {hr} BPM")
        if temp_alert:
            msg_parts.append(f"Temperature abnormal: {temp}°C")

        alert_text = " and ".join(msg_parts)
        voice_msg  = f"Warning! {alert_text}. Please check the elderly person immediately."

        # Voice alert
        try:
            subprocess.Popen(["espeak", "-s", "130", voice_msg],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

        # Telegram alert
        token   = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
        if token == "YOUR_BOT_TOKEN_HERE":
            return

        icons = "⚠️" * (int(hr_alert) + int(temp_alert))
        tg_msg = (
            f"{icons} HEALTH ALERT {icons}\n"
            f"Time: {timestamp}\n"
        )
        if hr_alert:
            tg_msg += f"❤️ Heart Rate: {hr} BPM (Normal: {config.HR_LOW}-{config.HR_HIGH})\n"
        if temp_alert:
            tg_msg += f"🌡️ Temperature: {temp}°C (Normal: {config.TEMP_LOW}-{config.TEMP_HIGH})\n"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": tg_msg}, timeout=8)
            log.info("Health alert sent via Telegram.")
        except Exception as e:
            log.error(f"Telegram health alert failed: {e}")

    # ----------------------------------------------------------
    def get_latest(self):
        """Thread-safe read of latest health data."""
        with self._lock:
            return dict(self._latest)

    # ----------------------------------------------------------
    def stop(self):
        self.running = False


# ============================================================
if __name__ == "__main__":
    monitor = HealthMonitor()
    monitor.start()
