"""
============================================================
  CareMate - Shared State Object
  ============================================================
  Thread-safe data store shared between all system modules:
    - Person following
    - Fall detection
    - Health monitoring
    - Voice assistant
    - Dashboard

  All modules read/write through this object instead of
  global variables, making multi-threading safe and clean.
============================================================
"""

import threading
import time
import cv2
import numpy as np
from datetime import datetime


class SharedState:
    """
    Central thread-safe state store for the CareMate system.
    """

    def __init__(self):
        self._lock  = threading.Lock()

        # ---- Camera frame (for dashboard MJPEG stream) ----
        self.latest_frame = None
        self.frame_lock   = threading.Lock()

        # ---- Health vitals ----
        self._health = {
            "hr":         0,
            "temp":       0.0,
            "hum":        0.0,
            "hr_alert":   False,
            "temp_alert": False,
            "timestamp":  None,
        }

        # ---- Fall detection ----
        self._fall = {
            "detected":  False,
            "last_time": None,
        }

        # ---- Robot status ----
        self._robot = {
            "mode":    "idle",      # 'idle' | 'following'
            "command": "STOP",
        }

        # ---- System info ----
        self._system = {
            "active":  True,
            "battery": 78,
            "network": "Connected",
        }

        # ---- Activity log ----
        self._activity = []

        # ---- Motor command queue (person following → main loop) ----
        self._pending_motor_cmd = None

        # ---- Voice assistant output ----
        self._voice_response = None

    # ----------------------------------------------------------
    #   Health
    # ----------------------------------------------------------
    def update_health(self, hr, temp, hum, hr_alert=False, temp_alert=False):
        with self._lock:
            self._health.update({
                "hr":         hr,
                "temp":       temp,
                "hum":        hum,
                "hr_alert":   hr_alert,
                "temp_alert": temp_alert,
                "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

    def get_health(self):
        with self._lock:
            return dict(self._health)

    # ----------------------------------------------------------
    #   Fall
    # ----------------------------------------------------------
    def set_fall_detected(self, detected: bool):
        with self._lock:
            self._fall["detected"]  = detected
            if detected:
                self._fall["last_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_fall(self):
        with self._lock:
            return dict(self._fall)

    # ----------------------------------------------------------
    #   Robot
    # ----------------------------------------------------------
    def set_robot_mode(self, mode: str):
        with self._lock:
            self._robot["mode"] = mode

    def set_robot_command(self, cmd: str):
        with self._lock:
            self._robot["command"]  = cmd
            self._pending_motor_cmd = cmd

    def pop_motor_command(self):
        """Get and clear pending motor command (from dashboard manual control)."""
        with self._lock:
            cmd = self._pending_motor_cmd
            self._pending_motor_cmd = None
            return cmd

    def get_robot(self):
        with self._lock:
            return dict(self._robot)

    # ----------------------------------------------------------
    #   System
    # ----------------------------------------------------------
    def get_system(self):
        with self._lock:
            return dict(self._system)

    # ----------------------------------------------------------
    #   Activity Log
    # ----------------------------------------------------------
    def add_activity(self, message: str):
        entry = {
            "time":    datetime.now().strftime("%I:%M:%S %p"),
            "message": message
        }
        with self._lock:
            self._activity.insert(0, entry)
            self._activity = self._activity[:50]

    def get_activity(self):
        with self._lock:
            return list(self._activity)

    # ----------------------------------------------------------
    #   Camera Frame
    # ----------------------------------------------------------
    def update_frame(self, frame):
        with self.frame_lock:
            self.latest_frame = frame.copy()

    def get_frame(self):
        with self.frame_lock:
            return self.latest_frame

    # ----------------------------------------------------------
    #   Dashboard-compatible dict (for /api/status endpoint)
    # ----------------------------------------------------------
    def to_dict(self):
        with self._lock:
            return {
                "health":   dict(self._health),
                "fall":     dict(self._fall),
                "robot":    dict(self._robot),
                "system":   dict(self._system),
                "activity": list(self._activity[:10]),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
