"""
============================================================
  CareMate - Full Integrated System
  ============================================================
  Main entry point that runs ALL CareMate modules together:

    Thread 1: Vision loop (person following + fall detection)
    Thread 2: Health monitoring (reads Arduino sensor data)
    Thread 3: Voice assistant (listen → respond)
    Thread 4: Flask dashboard (web UI + camera stream)
    Main:     Arduino serial management + heartbeat

  Start the system:
    cd full_system
    python main.py

  Stop:
    Press Ctrl+C

  Dashboard URL:
    http://<raspberry-pi-ip>:5000

  Prerequisites:
    1. Edit ../config.py with your Telegram token, Groq API key, serial port
    2. Flash caremate_arduino.ino to Arduino
    3. Connect Arduino via USB
    4. Run: pip install -r ../requirements.txt --break-system-packages
    5. Download YOLO models: python -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); YOLO('yolov8n-pose.pt')"
============================================================
"""

import sys
import os
import time
import threading
import logging
import signal
import serial

# ---- Path setup ----
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'module_01_person_following'))
sys.path.insert(0, os.path.join(ROOT, 'module_02_fall_detection'))
sys.path.insert(0, os.path.join(ROOT, 'module_03_health_monitoring'))
sys.path.insert(0, os.path.join(ROOT, 'module_04_voice_assistant'))
sys.path.insert(0, os.path.join(ROOT, 'module_05_dashboard_alerts'))

import config
from shared_state import SharedState

# ---- Logging ----
os.makedirs(config.LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(config.LOG_DIR, "caremate.log"))
    ]
)
log = logging.getLogger("CAREMATE")

# ---- Import modules ----
try:
    import cv2
    from ultralytics import YOLO
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    log.warning("OpenCV / YOLO not available - vision disabled")

try:
    from person_following import PersonFollower
    FOLLOWING_AVAILABLE = True
except ImportError as e:
    FOLLOWING_AVAILABLE = False
    log.warning(f"Person following module unavailable: {e}")

try:
    from fall_detection import FallDetector
    FALL_AVAILABLE = True
except ImportError as e:
    FALL_AVAILABLE = False
    log.warning(f"Fall detection module unavailable: {e}")

try:
    from health_monitor import HealthMonitor
    HEALTH_AVAILABLE = True
except ImportError as e:
    HEALTH_AVAILABLE = False
    log.warning(f"Health monitor unavailable: {e}")

try:
    from voice_assistant import VoiceAssistant
    VOICE_AVAILABLE = True
except ImportError as e:
    VOICE_AVAILABLE = False
    log.warning(f"Voice assistant unavailable: {e}")

try:
    from app import app as flask_app, add_activity
    from telegram_bot import send_system_start
    DASH_AVAILABLE = True
except ImportError as e:
    DASH_AVAILABLE = False
    log.warning(f"Dashboard unavailable: {e}")


# ============================================================
class CareMateSystem:
    """
    Orchestrates all CareMate modules.
    Uses SharedState for thread-safe inter-module communication.
    """

    def __init__(self):
        self.state      = SharedState()
        self.running    = False
        self.threads    = []
        self.ser        = None   # Shared serial connection to Arduino

        # Module instances
        self.follower   = None
        self.detector   = None
        self.health_mon = None
        self.voice      = None

    # ----------------------------------------------------------
    def start(self):
        """Initialize everything and launch all threads."""
        log.info("=" * 55)
        log.info("   CareMate AI Elderly Care Companion - Starting")
        log.info("=" * 55)

        self.running = True
        self._connect_arduino()

        # ---- Launch threads ----
        thread_configs = [
            ("Vision",   self._vision_thread,   CV_AVAILABLE),
            ("Health",   self._health_thread,   HEALTH_AVAILABLE),
            ("Voice",    self._voice_thread,    VOICE_AVAILABLE),
            ("Dashboard",self._dashboard_thread, DASH_AVAILABLE),
        ]

        for name, target, available in thread_configs:
            if available:
                t = threading.Thread(target=target, name=name, daemon=True)
                t.start()
                self.threads.append(t)
                log.info(f"Thread [{name}] started.")
            else:
                log.warning(f"Thread [{name}] SKIPPED (module not available).")

        # Notify caregiver
        if DASH_AVAILABLE:
            try:
                send_system_start()
            except Exception:
                pass

        self.state.add_activity("CareMate system started")
        log.info("All threads launched. System running.")
        log.info(f"Dashboard: http://0.0.0.0:{config.FLASK_PORT}")

        # ---- Main loop: heartbeat + manual command forwarding ----
        self._main_loop()

    # ----------------------------------------------------------
    def _connect_arduino(self):
        """Open single shared serial connection to Arduino."""
        log.info(f"Connecting to Arduino on {config.SERIAL_PORT}...")
        try:
            self.ser = serial.Serial(config.SERIAL_PORT, config.BAUD_RATE,
                                     timeout=config.SERIAL_TIMEOUT)
            time.sleep(2)   # Arduino reset grace period
            log.info("Arduino connected.")
            self.state.add_activity("Arduino connected")
        except serial.SerialException as e:
            log.warning(f"Arduino not found: {e}. Running in simulation mode.")
            self.ser = None

    # ----------------------------------------------------------
    def _main_loop(self):
        """
        Main thread loop:
        - Sends heartbeat 'K' to Arduino every second
        - Forwards any manual dashboard commands to Arduino
        """
        last_hb = time.time()

        try:
            while self.running:
                now = time.time()

                # Send heartbeat every 1 second
                if now - last_hb >= 1.0:
                    self._serial_write(b'K')
                    last_hb = now

                # Forward any pending manual command from dashboard
                cmd = self.state.pop_motor_command()
                if cmd:
                    self._serial_write(cmd.encode())

                time.sleep(0.05)

        except KeyboardInterrupt:
            log.info("Ctrl+C received. Shutting down...")
        finally:
            self._shutdown()

    # ----------------------------------------------------------
    def _vision_thread(self):
        """
        Vision thread: runs both person following AND fall detection
        on every camera frame. Uses a single camera instance.
        """
        log.info("[Vision] Loading YOLO models...")
        try:
            detect_model = YOLO(config.YOLO_DETECT_MODEL)
            pose_model   = YOLO(config.YOLO_POSE_MODEL)
        except Exception as e:
            log.error(f"[Vision] Failed to load YOLO: {e}")
            return

        log.info(f"[Vision] Opening camera {config.CAMERA_INDEX}...")
        cap = cv2.VideoCapture(config.CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        if not cap.isOpened():
            log.error("[Vision] Cannot open camera!")
            return

        # Fall detection state
        fall_frame_count  = 0
        last_fall_alert   = 0
        last_cmd          = None
        frame_w = config.FRAME_WIDTH
        frame_h = config.FRAME_HEIGHT
        last_hb = time.time()

        log.info("[Vision] Loop started.")
        self.state.add_activity("Camera and vision started")

        try:
            while self.running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                frame_h, frame_w = frame.shape[:2]
                display = frame.copy()

                robot_mode = self.state.get_robot()["mode"]

                # ============ PERSON FOLLOWING ============
                if robot_mode == "following":
                    results = detect_model(frame,
                                           conf=config.CONFIDENCE,
                                           classes=[0],
                                           verbose=False)
                    target_box = self._pick_largest_box(results, frame_w, frame_h)

                    if target_box:
                        x1, y1, x2, y2 = target_box
                        cmd = self._compute_motor_cmd(x1, y1, x2, y2, frame_w, frame_h)
                        if cmd != last_cmd:
                            self._serial_write(cmd)
                            last_cmd = cmd
                            self.state._robot["command"] = cmd.decode()

                        # Draw tracking box
                        cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(display, f"COMMAND: {cmd.decode()}", (20, 40),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                        cv2.line(display, (frame_w // 2, 0), (frame_w // 2, frame_h),
                                 (255, 0, 0), 1)
                    else:
                        if last_cmd != b'S':
                            self._serial_write(b'S')
                            last_cmd = b'S'

                # ============ FALL DETECTION ============
                pose_results = pose_model(frame,
                                          conf=config.CONFIDENCE,
                                          classes=[0],
                                          verbose=False)
                fall_this_frame = False

                for result in pose_results:
                    if result.boxes is None:
                        continue
                    for i, box in enumerate(result.boxes):
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        w, h = x2 - x1, y2 - y1
                        if w < config.MIN_BOX_WIDTH or h < config.MIN_BOX_HEIGHT:
                            continue
                        aspect = w / max(h, 1)
                        if aspect > config.FALL_ASPECT_RATIO:
                            fall_this_frame = True
                        # Draw pose box
                        color = (0, 0, 255) if fall_this_frame else (0, 200, 100)
                        cv2.rectangle(display, (x1, y1), (x2, y2), color, 1)

                        # Draw keypoints
                        if result.keypoints and i < len(result.keypoints.xy):
                            kps = result.keypoints.xy[i].cpu().numpy()
                            for kx, ky in kps:
                                if kx > 0 and ky > 0:
                                    cv2.circle(display, (int(kx), int(ky)), 3, (0, 255, 255), -1)

                # Fall confirmation
                if fall_this_frame:
                    fall_frame_count += 1
                else:
                    fall_frame_count = max(0, fall_frame_count - 1)

                cooldown_ok = (time.time() - last_fall_alert) > config.FALL_COOLDOWN_SEC
                if (fall_frame_count >= config.FALL_CONFIRM_FRAMES) and cooldown_ok:
                    last_fall_alert  = time.time()
                    fall_frame_count = 0
                    log.warning("[Vision] FALL CONFIRMED!")
                    self.state.set_fall_detected(True)
                    self.state.add_activity("⚠️ FALL DETECTED")
                    # Save snapshot and alert in background
                    snap_path = config.FALL_SNAPSHOT_PATH
                    cv2.imwrite(snap_path, display)
                    t = threading.Thread(target=self._fall_alert, args=(snap_path,), daemon=True)
                    t.start()

                # Fall status overlay
                if self.state.get_fall()["detected"]:
                    cv2.putText(display, "FALL DETECTED", (20, frame_h - 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)

                # Share annotated frame with dashboard
                self.state.update_frame(display)

                # Heartbeat to Arduino
                now = time.time()
                if now - last_hb >= 1.0:
                    self._serial_write(b'K')
                    last_hb = now

        except Exception as e:
            log.error(f"[Vision] Thread crashed: {e}", exc_info=True)
        finally:
            cap.release()
            log.info("[Vision] Thread stopped.")

    # ----------------------------------------------------------
    def _health_thread(self):
        """Health monitoring thread: reads Arduino sensor data."""
        try:
            monitor = HealthMonitor(serial_conn=self.ser)

            def on_reading(hr, temp, hum, hr_alert, temp_alert):
                self.state.update_health(hr, temp, hum, hr_alert, temp_alert)
                if hr_alert or temp_alert:
                    self.state.add_activity(
                        f"⚠️ Health alert: HR={hr} Temp={temp}°C"
                    )

            # Patch process method to update shared state
            original_process = monitor._process_reading

            def patched_process(hr, temp, hum):
                original_process(hr, temp, hum)
                with monitor._lock:
                    d = monitor._latest
                    self.state.update_health(d["hr"], d["temp"], d["hum"],
                                             d["hr_alert"], d["temp_alert"])

            monitor._process_reading = patched_process
            monitor.ser = self.ser
            monitor._owns_serial = False
            monitor.start()

        except Exception as e:
            log.error(f"[Health] Thread crashed: {e}", exc_info=True)

    # ----------------------------------------------------------
    def _voice_thread(self):
        """Voice assistant thread."""
        try:
            assistant = VoiceAssistant(shared_state=self.state)
            assistant.start()
        except Exception as e:
            log.error(f"[Voice] Thread crashed: {e}", exc_info=True)

    # ----------------------------------------------------------
    def _dashboard_thread(self):
        """Flask dashboard thread."""
        try:
            # Patch app state to use our shared state
            import app as dash_app

            # Override the /api/status route to use shared state
            @flask_app.route('/api/status_live')
            def status_live():
                from flask import jsonify
                return jsonify(self.state.to_dict())

            # Patch frame provider for video feed
            original_latest = dash_app._state
            dash_app._state["frame_lock"] = self.state.frame_lock

            # Proxy latest_frame to shared state
            class FrameProxy(dict):
                def __getitem__(self, key):
                    if key == 'latest_frame':
                        return self._shared.get_frame()
                    return super().__getitem__(key)

            dash_app.run_dashboard(debug=False)
        except Exception as e:
            log.error(f"[Dashboard] Thread crashed: {e}", exc_info=True)

    # ----------------------------------------------------------
    def _fall_alert(self, snapshot_path):
        """Send fall alert via Telegram (called in background thread)."""
        import subprocess
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        # Voice alert
        try:
            subprocess.Popen(["espeak", "-s", "130",
                              "Alert! A fall has been detected. Please check immediately."],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

        # Telegram
        if DASH_AVAILABLE:
            from telegram_bot import send_fall_alert
            send_fall_alert(snapshot_path, ts)

        # Auto-clear fall status after 30 seconds
        time.sleep(30)
        self.state.set_fall_detected(False)

    # ----------------------------------------------------------
    def _pick_largest_box(self, results, frame_w, frame_h):
        """Pick largest valid bounding box from YOLO results."""
        best_area = 0
        best_box  = None
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                w, h = x2 - x1, y2 - y1
                if w < config.MIN_BOX_WIDTH or h < config.MIN_BOX_HEIGHT:
                    continue
                area = w * h
                if area > best_area:
                    best_area = area
                    best_box  = (x1, y1, x2, y2)
        return best_box

    # ----------------------------------------------------------
    def _compute_motor_cmd(self, x1, y1, x2, y2, frame_w, frame_h):
        """Calculate motor command from person position."""
        person_cx = (x1 + x2) // 2
        frame_cx  = frame_w // 2
        box_h     = y2 - y1
        h_ratio   = box_h / frame_h
        dead_zone = int(frame_w * config.DEAD_ZONE_RATIO)

        if h_ratio > config.CLOSE_ZONE_RATIO:
            return b'S'
        error = person_cx - frame_cx
        if error > dead_zone:
            return b'R'
        elif error < -dead_zone:
            return b'L'
        return b'F'

    # ----------------------------------------------------------
    def _serial_write(self, data: bytes):
        """Thread-safe serial write to Arduino."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(data)
            except serial.SerialException:
                pass

    # ----------------------------------------------------------
    def _shutdown(self):
        """Clean shutdown of all modules."""
        log.info("Shutting down CareMate...")
        self.running = False

        # Stop motors
        self._serial_write(b'S')
        time.sleep(0.2)

        if self.ser and self.ser.is_open:
            self.ser.close()
            log.info("Serial port closed.")

        log.info("CareMate stopped. Goodbye.")


# ============================================================
def main():
    system = CareMateSystem()

    # Handle Ctrl+C gracefully
    def handler(sig, frame):
        log.info("Interrupt received.")
        system.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT,  handler)
    signal.signal(signal.SIGTERM, handler)

    system.start()


if __name__ == "__main__":
    main()
