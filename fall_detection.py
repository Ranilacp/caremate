"""
============================================================
  CareMate - Module 02: Fall Detection
  ============================================================
  Uses YOLOv8n-pose to detect human pose keypoints.

  Fall Detection Logic:
    1. Get bounding box of detected person
    2. Calculate aspect ratio: width / height
    3. If ratio > threshold → person is horizontal (fallen)
    4. Additionally check keypoints: head y-position vs hip y-position
    5. Confirm fall over N consecutive frames (avoid false alerts)
    6. On confirmed fall:
       - Capture snapshot image
       - Send Telegram message + photo to caregiver
       - Play espeak voice alert
    7. Enforce cooldown between alerts

  Keypoints (YOLOv8-pose, COCO format, 17 keypoints):
    0=nose  1=left_eye  2=right_eye  3=left_ear  4=right_ear
    5=left_shoulder  6=right_shoulder
    7=left_elbow     8=right_elbow
    9=left_wrist    10=right_wrist
    11=left_hip     12=right_hip
    13=left_knee    14=right_knee
    15=left_ankle   16=right_ankle

  Run standalone:
    python fall_detection.py
============================================================
"""

import cv2
import sys
import os
import time
import logging
import subprocess
import requests
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [FALL] %(message)s')
log = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    import numpy as np
except ImportError:
    log.error("Install: pip install ultralytics numpy --break-system-packages")
    sys.exit(1)

# Keypoint indices (COCO)
KP_NOSE         = 0
KP_LEFT_EYE     = 1
KP_RIGHT_EYE    = 2
KP_LEFT_SHOULDER  = 5
KP_RIGHT_SHOULDER = 6
KP_LEFT_HIP     = 11
KP_RIGHT_HIP    = 12


class FallDetector:
    """
    Real-time fall detection using YOLOv8n-pose.
    Sends Telegram alerts on confirmed fall events.
    """

    def __init__(self, alert_callback=None, show_preview=None):
        """
        Args:
            alert_callback: Optional function(image_path) called on fall.
                            If None, sends Telegram alert internally.
            show_preview:   Override config.SHOW_PREVIEW.
        """
        self.alert_callback = alert_callback
        self.show_preview   = show_preview if show_preview is not None else config.SHOW_PREVIEW

        self.model    = None
        self.cap      = None
        self.running  = False

        # Fall confirmation state
        self.fall_frame_count = 0
        self.last_alert_time  = 0
        self.fall_confirmed   = False

    # ----------------------------------------------------------
    def start(self):
        log.info("Loading YOLOv8n-pose model...")
        self.model = YOLO(config.YOLO_POSE_MODEL)
        log.info("Pose model loaded.")

        log.info(f"Opening camera index {config.CAMERA_INDEX}...")
        self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        if not self.cap.isOpened():
            log.error("Cannot open camera!")
            return

        self.running = True
        log.info("Fall detection started. Press Ctrl+C to stop.")
        self._loop()

    # ----------------------------------------------------------
    def _loop(self):
        try:
            while self.running:
                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                frame_h, frame_w = frame.shape[:2]

                results = self.model(frame,
                                     conf=config.CONFIDENCE,
                                     classes=[0],
                                     verbose=False)

                fall_detected_this_frame = False
                display_frame = frame.copy()

                for result in results:
                    boxes = result.boxes
                    kpts  = result.keypoints

                    if boxes is None or len(boxes) == 0:
                        continue

                    for i, box in enumerate(boxes):
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        w = x2 - x1
                        h = y2 - y1

                        if w < config.MIN_BOX_WIDTH or h < config.MIN_BOX_HEIGHT:
                            continue

                        # ---- Check 1: Bounding Box Aspect Ratio ----
                        aspect_ratio = w / max(h, 1)
                        ratio_fallen = aspect_ratio > config.FALL_ASPECT_RATIO

                        # ---- Check 2: Keypoint Head vs Hip ----
                        kp_fallen = False
                        if kpts is not None and i < len(kpts.xy):
                            keypoints = kpts.xy[i].cpu().numpy()
                            kp_fallen = self._check_keypoints_fallen(keypoints, frame_h)

                        # Either check can trigger fall
                        is_fallen = ratio_fallen or kp_fallen

                        if is_fallen:
                            fall_detected_this_frame = True
                            color = (0, 0, 255)   # Red box = fallen
                        else:
                            color = (0, 255, 0)   # Green box = standing

                        # Draw bounding box
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                        conf_val = float(box.conf[0])
                        label = f"person {conf_val:.2f}"
                        cv2.putText(display_frame, label, (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                        # Draw keypoints if available
                        if kpts is not None and i < len(kpts.xy):
                            self._draw_keypoints(display_frame, kpts.xy[i].cpu().numpy())

                # ---- Fall Confirmation Logic ----
                if fall_detected_this_frame:
                    self.fall_frame_count += 1
                else:
                    self.fall_frame_count = max(0, self.fall_frame_count - 1)

                confirmed_now = self.fall_frame_count >= config.FALL_CONFIRM_FRAMES
                cooldown_ok   = (time.time() - self.last_alert_time) > config.FALL_COOLDOWN_SEC

                if confirmed_now and cooldown_ok:
                    self.last_alert_time = time.time()
                    self.fall_frame_count = 0
                    log.warning("FALL CONFIRMED! Triggering alert.")
                    self._on_fall_confirmed(display_frame)

                # ---- Display ----
                status_text = "FALL DETECTED" if fall_detected_this_frame else "MONITORING"
                status_color = (0, 0, 255) if fall_detected_this_frame else (0, 200, 0)
                cv2.putText(display_frame, status_text, (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 3)
                cv2.putText(display_frame, f"Confirm: {self.fall_frame_count}/{config.FALL_CONFIRM_FRAMES}",
                            (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                if self.show_preview:
                    cv2.imshow("CareMate - Fall Detection", display_frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
        finally:
            self._cleanup()

    # ----------------------------------------------------------
    def _check_keypoints_fallen(self, keypoints, frame_h):
        """
        Returns True if head keypoints are at or below hip keypoints
        (indicating a fallen / horizontal posture).
        keypoints: numpy array of shape (17, 2) - x, y coordinates
        """
        try:
            # Head: average of nose, left eye, right eye
            head_kps = [keypoints[KP_NOSE], keypoints[KP_LEFT_EYE], keypoints[KP_RIGHT_EYE]]
            valid_head = [(x, y) for x, y in head_kps if x > 0 and y > 0]

            # Hip: average of left and right hip
            hip_kps = [keypoints[KP_LEFT_HIP], keypoints[KP_RIGHT_HIP]]
            valid_hip = [(x, y) for x, y in hip_kps if x > 0 and y > 0]

            if not valid_head or not valid_hip:
                return False

            head_y = sum(y for _, y in valid_head) / len(valid_head)
            hip_y  = sum(y for _, y in valid_hip)  / len(valid_hip)

            # In image coordinates, Y increases downward.
            # If head_y >= hip_y - margin → head is at or below hip level → fallen
            margin = frame_h * 0.05
            return head_y >= (hip_y - margin)

        except (IndexError, ZeroDivisionError):
            return False

    # ----------------------------------------------------------
    def _draw_keypoints(self, frame, keypoints, radius=4):
        """Draw skeleton keypoints on frame."""
        skeleton_pairs = [
            (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),
            (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16)
        ]
        for x, y in keypoints:
            if x > 0 and y > 0:
                cv2.circle(frame, (int(x), int(y)), radius, (0, 255, 255), -1)

        for a, b in skeleton_pairs:
            xa, ya = keypoints[a]
            xb, yb = keypoints[b]
            if xa > 0 and ya > 0 and xb > 0 and yb > 0:
                cv2.line(frame, (int(xa), int(ya)), (int(xb), int(yb)), (0, 165, 255), 2)

    # ----------------------------------------------------------
    def _on_fall_confirmed(self, frame):
        """Handle a confirmed fall event."""
        # Save snapshot
        snapshot_path = config.FALL_SNAPSHOT_PATH
        cv2.imwrite(snapshot_path, frame)
        log.info(f"Snapshot saved: {snapshot_path}")

        # Run alert in background thread (non-blocking)
        t = threading.Thread(
            target=self._send_alerts,
            args=(snapshot_path,),
            daemon=True
        )
        t.start()

    # ----------------------------------------------------------
    def _send_alerts(self, snapshot_path):
        """Send Telegram alert + voice alert."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # Voice alert
        self._voice_alert("Alert! A fall has been detected. Please check immediately.")

        # Callback (if used in full system)
        if self.alert_callback:
            self.alert_callback(snapshot_path)
            return

        # Direct Telegram send
        self._send_telegram_alert(snapshot_path, timestamp)

    # ----------------------------------------------------------
    def _send_telegram_alert(self, snapshot_path, timestamp):
        """Send photo + message to caregiver via Telegram."""
        token   = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID

        if token == "YOUR_BOT_TOKEN_HERE":
            log.warning("Telegram token not configured. Skipping alert.")
            return

        caption = (
            f"⚠️ FALL DETECTED\n"
            f"Time: {timestamp}\n"
            f"Awaiting caregiver confirmation"
        )

        # Inline keyboard
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Confirm Emergency", "callback_data": "confirm_emergency"},
                {"text": "❌ False Alarm",        "callback_data": "false_alarm"}
            ]]
        }

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        try:
            with open(snapshot_path, 'rb') as photo:
                resp = requests.post(url, data={
                    "chat_id":      chat_id,
                    "caption":      caption,
                    "reply_markup": str(reply_markup).replace("'", '"')
                }, files={"photo": photo}, timeout=10)
            if resp.status_code == 200:
                log.info("Telegram alert sent successfully.")
            else:
                log.error(f"Telegram error: {resp.text}")
        except Exception as e:
            log.error(f"Telegram send failed: {e}")

    # ----------------------------------------------------------
    @staticmethod
    def _voice_alert(message):
        """Speak alert using espeak."""
        try:
            subprocess.Popen(
                ["espeak", "-s", "130", message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            log.warning("espeak not installed. Install: sudo apt install espeak")

    # ----------------------------------------------------------
    def process_frame(self, frame):
        """
        Process a single frame externally (used by full_system/main.py).
        Returns: (annotated_frame, is_fall_confirmed)
        """
        frame_h, frame_w = frame.shape[:2]
        fall_detected_this_frame = False
        display_frame = frame.copy()

        results = self.model(frame, conf=config.CONFIDENCE, classes=[0], verbose=False)

        for result in results:
            boxes = result.boxes
            kpts  = result.keypoints
            if boxes is None:
                continue
            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                w, h = x2 - x1, y2 - y1
                if w < config.MIN_BOX_WIDTH or h < config.MIN_BOX_HEIGHT:
                    continue
                aspect_ratio = w / max(h, 1)
                ratio_fallen = aspect_ratio > config.FALL_ASPECT_RATIO
                kp_fallen = False
                if kpts is not None and i < len(kpts.xy):
                    kp_fallen = self._check_keypoints_fallen(kpts.xy[i].cpu().numpy(), frame_h)
                if ratio_fallen or kp_fallen:
                    fall_detected_this_frame = True
                color = (0, 0, 255) if (ratio_fallen or kp_fallen) else (0, 255, 0)
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)

        if fall_detected_this_frame:
            self.fall_frame_count += 1
        else:
            self.fall_frame_count = max(0, self.fall_frame_count - 1)

        cooldown_ok = (time.time() - self.last_alert_time) > config.FALL_COOLDOWN_SEC
        confirmed   = (self.fall_frame_count >= config.FALL_CONFIRM_FRAMES) and cooldown_ok

        if confirmed:
            self.last_alert_time  = time.time()
            self.fall_frame_count = 0

        return display_frame, confirmed

    # ----------------------------------------------------------
    def _cleanup(self):
        if self.cap:
            self.cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()
        log.info("Fall detection stopped.")

    def stop(self):
        self.running = False


# ============================================================
if __name__ == "__main__":
    detector = FallDetector()
    detector.start()
