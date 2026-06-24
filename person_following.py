"""
============================================================
  CareMate - Module 01: Person Detection & Following
  ============================================================
  Uses YOLOv8n to detect a person and sends motor commands
  to the Arduino via serial to keep the person centered
  in the camera frame.

  How It Works:
    1. Camera captures frame
    2. YOLOv8n detects all 'person' class objects
    3. Picks the LARGEST bounding box (assumed = closest person)
    4. Filters out tiny boxes (chair legs, distant people)
    5. Calculates error (how far person is from frame center)
    6. Sends motor command: LEFT / RIGHT / FORWARD / STOP
    7. Only sends command when state changes (avoids serial flood)

  Run standalone:
    python person_following.py

  Press 'q' to quit (if SHOW_PREVIEW = True)
============================================================
"""

import cv2
import serial
import time
import sys
import os
import logging

# Add parent directory to import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [FOLLOW] %(message)s')
log = logging.getLogger(__name__)

# ---- Try importing YOLO ----
try:
    from ultralytics import YOLO
except ImportError:
    log.error("ultralytics not installed. Run: pip install ultralytics --break-system-packages")
    sys.exit(1)


# ============================================================
#   Motor Command Map
# ============================================================
CMD_FORWARD  = b'F'
CMD_LEFT     = b'L'
CMD_RIGHT    = b'R'
CMD_STOP     = b'S'
CMD_BACKWARD = b'B'


class PersonFollower:
    """
    Detects and follows a person using YOLOv8n and serial motor commands.
    """

    def __init__(self, serial_port=None, show_preview=None):
        self.serial_port   = serial_port or config.SERIAL_PORT
        self.show_preview  = show_preview if show_preview is not None else config.SHOW_PREVIEW

        self.model         = None
        self.cap           = None
        self.ser           = None

        self.last_command  = None       # State-change tracking
        self.miss_count    = 0          # Consecutive frames with no person
        self.MAX_MISS      = 10         # Stop after this many missed frames

        self.running       = False

        # Frame dimensions (set after camera init)
        self.frame_w       = config.FRAME_WIDTH
        self.frame_h       = config.FRAME_HEIGHT

        # Heartbeat tracking
        self.last_hb_time  = time.time()

    # ----------------------------------------------------------
    def start(self):
        """Initialize all resources and begin tracking loop."""
        log.info("Loading YOLOv8n model...")
        self.model = YOLO(config.YOLO_DETECT_MODEL)
        log.info("Model loaded.")

        log.info(f"Opening camera index {config.CAMERA_INDEX}...")
        self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.frame_w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_h)

        if not self.cap.isOpened():
            log.error("Cannot open camera!")
            return

        log.info(f"Connecting to Arduino on {self.serial_port}...")
        try:
            self.ser = serial.Serial(self.serial_port, config.BAUD_RATE,
                                     timeout=config.SERIAL_TIMEOUT)
            time.sleep(2)  # Arduino resets on serial open
            log.info("Arduino connected.")
        except serial.SerialException as e:
            log.warning(f"Serial not available: {e}. Running in camera-only mode.")
            self.ser = None

        self.running = True
        log.info("Person following started. Press Ctrl+C to stop.")
        self._loop()

    # ----------------------------------------------------------
    def _loop(self):
        """Main detection and control loop."""
        try:
            while self.running:
                ret, frame = self.cap.read()
                if not ret:
                    log.warning("Camera read failed.")
                    time.sleep(0.1)
                    continue

                self.frame_h, self.frame_w = frame.shape[:2]

                # ---- Heartbeat: send 'K' to Arduino ----
                self._send_heartbeat()

                # ---- Detect persons ----
                results = self.model(frame,
                                     conf=config.CONFIDENCE,
                                     classes=[0],       # 0 = person
                                     verbose=False)

                target_box = self._pick_target(results)

                if target_box is not None:
                    self.miss_count = 0
                    x1, y1, x2, y2 = target_box
                    cmd = self._compute_command(x1, y1, x2, y2)
                    self._send_command(cmd)

                    if self.show_preview:
                        self._draw_box(frame, x1, y1, x2, y2, cmd)
                else:
                    self.miss_count += 1
                    if self.miss_count >= self.MAX_MISS:
                        self._send_command(CMD_STOP)
                        if self.show_preview:
                            cv2.putText(frame, "NO TARGET - STOPPED",
                                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                                        0.8, (0, 0, 255), 2)

                if self.show_preview:
                    cv2.imshow("CareMate - Person Following", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

                time.sleep(config.MOTOR_COMMAND_DELAY)

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
        finally:
            self._cleanup()

    # ----------------------------------------------------------
    def _pick_target(self, results):
        """
        From all detected persons, return the bounding box of the
        LARGEST one (closest to camera), filtering out tiny boxes.
        Returns (x1, y1, x2, y2) or None.
        """
        best_area = 0
        best_box  = None

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                w = x2 - x1
                h = y2 - y1

                # Filter: too small = chair leg or distant person
                if w < config.MIN_BOX_WIDTH or h < config.MIN_BOX_HEIGHT:
                    continue

                area = w * h
                if area > best_area:
                    best_area = area
                    best_box  = (x1, y1, x2, y2)

        return best_box

    # ----------------------------------------------------------
    def _compute_command(self, x1, y1, x2, y2):
        """
        Decide motor command based on person's position in frame.

        Zones (horizontal):
          |  LEFT  |  CENTER (dead zone)  |  RIGHT  |

        Distance (vertical - box height as fraction of frame):
          > CLOSE_ZONE → STOP (too close)
          < FAR_ZONE   → FORWARD (too far - shouldn't turn)
          else         → FORWARD at normal speed
        """
        person_cx = (x1 + x2) // 2
        frame_cx  = self.frame_w // 2

        box_h     = y2 - y1
        h_ratio   = box_h / self.frame_h

        dead_zone = int(self.frame_w * config.DEAD_ZONE_RATIO)

        # Check distance
        if h_ratio > config.CLOSE_ZONE_RATIO:
            return CMD_STOP   # Too close

        # Check horizontal position
        error = person_cx - frame_cx

        if error > dead_zone:
            return CMD_RIGHT
        elif error < -dead_zone:
            return CMD_LEFT
        else:
            return CMD_FORWARD

    # ----------------------------------------------------------
    def _send_command(self, cmd):
        """Send command to Arduino only if it changed (avoid serial flood)."""
        if cmd == self.last_command:
            return

        cmd_str = cmd.decode()
        log.info(f"COMMAND: {self._cmd_name(cmd)}")

        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd)
            except serial.SerialException as e:
                log.error(f"Serial write error: {e}")

        self.last_command = cmd

    # ----------------------------------------------------------
    def _send_heartbeat(self):
        """Send 'K' to Arduino every second to prevent safety stop."""
        now = time.time()
        if now - self.last_hb_time >= 1.0:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(b'K')
                except Exception:
                    pass
            self.last_hb_time = now

    # ----------------------------------------------------------
    def _draw_box(self, frame, x1, y1, x2, y2, cmd):
        """Draw detection box and command label on preview frame."""
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"COMMAND: {self._cmd_name(cmd)}"
        cv2.putText(frame, label, (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        # Draw center lines
        cv2.line(frame, (self.frame_w // 2, 0),
                 (self.frame_w // 2, self.frame_h), (255, 0, 0), 1)
        cx = (x1 + x2) // 2
        cv2.circle(frame, (cx, (y1 + y2) // 2), 6, (0, 0, 255), -1)

    # ----------------------------------------------------------
    @staticmethod
    def _cmd_name(cmd):
        names = {b'F': 'MOVE FORWARD', b'B': 'MOVE BACKWARD',
                 b'L': 'MOVE LEFT',    b'R': 'MOVE RIGHT',
                 b'S': 'STOP'}
        return names.get(cmd, 'UNKNOWN')

    # ----------------------------------------------------------
    def _cleanup(self):
        log.info("Cleaning up...")
        if self.ser and self.ser.is_open:
            self.ser.write(CMD_STOP)
            self.ser.close()
        if self.cap:
            self.cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()
        log.info("Person following stopped.")

    # ----------------------------------------------------------
    def stop(self):
        """External stop (called from full_system/main.py)."""
        self.running = False


# ============================================================
if __name__ == "__main__":
    follower = PersonFollower()
    follower.start()
