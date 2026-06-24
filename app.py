"""
============================================================
  CareMate - Module 05: Caregiver Dashboard & Alert System
  ============================================================
  Flask web application providing:
    - Live MJPEG camera stream
    - Real-time vitals display (HR, Temperature)
    - Fall alert status
    - Activity log
    - Manual robot control buttons
    - Telegram alert integration

  Access on local network:
    http://<raspberry-pi-ip>:5000

  Run standalone:
    python app.py

  In full system: imported and run in background thread.
============================================================
"""

import cv2
import sys
import os
import json
import time
import threading
import logging
from datetime import datetime
from flask import Flask, Response, render_template, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [DASH] %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ---- Shared state (replaced by SharedState in full_system) ----
_state = {
    "health":     {"hr": 0, "temp": 0.0, "hum": 0.0, "hr_alert": False, "temp_alert": False},
    "fall":       {"detected": False, "last_time": None},
    "robot":      {"mode": "idle", "command": "STOP"},
    "system":     {"active": True, "battery": 78, "network": "Connected"},
    "activity":   [],   # List of {time, message} dicts
    "latest_frame": None,  # numpy array (shared with camera thread)
    "frame_lock":  threading.Lock(),
}


def get_state():
    """Get the global state (or SharedState if injected)."""
    return _state


def set_shared_state(shared):
    """Called by full_system/main.py to inject shared state."""
    global _state
    _state = shared


# ----------------------------------------------------------
def add_activity(message):
    """Add entry to activity log (newest first, max 50 entries)."""
    entry = {
        "time":    datetime.now().strftime("%I:%M:%S %p"),
        "message": message
    }
    _state["activity"].insert(0, entry)
    _state["activity"] = _state["activity"][:50]


# ============================================================
#   Camera Feed
# ============================================================
def gen_frames():
    """MJPEG frame generator for /video_feed route."""
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

    while True:
        # If full_system provides annotated frames via shared state
        with _state.get("frame_lock", threading.Lock()):
            annotated = _state.get("latest_frame")

        if annotated is not None:
            frame = annotated
        else:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.05)   # ~20 FPS


# ============================================================
#   Routes
# ============================================================
@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Live MJPEG camera stream."""
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/status')
def api_status():
    """Return current system status as JSON (polled by dashboard JS)."""
    st = get_state()
    health   = st.get("health", {})
    fall     = st.get("fall",   {})
    robot    = st.get("robot",  {})
    system   = st.get("system", {})
    activity = st.get("activity", [])

    return jsonify({
        "health":     health,
        "fall":       fall,
        "robot":      robot,
        "system":     system,
        "activity":   activity[:10],   # Last 10 entries
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route('/api/manual_command', methods=['POST'])
def api_manual_command():
    """Send manual motor command (from dashboard manual control buttons)."""
    data = request.get_json()
    cmd  = data.get("command", "S").upper()
    if cmd in ('F', 'B', 'L', 'R', 'S'):
        _state["robot"]["command"] = cmd
        add_activity(f"Manual command: {cmd}")
        log.info(f"Manual command received: {cmd}")
        return jsonify({"status": "ok", "command": cmd})
    return jsonify({"status": "error", "message": "Invalid command"}), 400


@app.route('/api/start_tracking', methods=['POST'])
def api_start_tracking():
    _state["robot"]["mode"] = "following"
    add_activity("Person following started")
    return jsonify({"status": "ok"})


@app.route('/api/stop_tracking', methods=['POST'])
def api_stop_tracking():
    _state["robot"]["mode"] = "idle"
    _state["robot"]["command"] = "S"
    add_activity("Tracking stopped")
    return jsonify({"status": "ok"})


@app.route('/api/simulate_fall', methods=['POST'])
def api_simulate_fall():
    """Demo button: simulate a fall detection event."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _state["fall"]["detected"] = True
    _state["fall"]["last_time"] = ts
    add_activity("⚠️ FALL DETECTED (simulated)")
    log.info("Fall simulation triggered from dashboard.")
    return jsonify({"status": "ok", "message": "Fall simulated"})


@app.route('/api/clear_fall', methods=['POST'])
def api_clear_fall():
    _state["fall"]["detected"] = False
    add_activity("Fall alert cleared")
    return jsonify({"status": "ok"})


@app.route('/api/alerts')
def api_alerts():
    """Return recent activity log."""
    return jsonify({"alerts": _state.get("activity", [])})


# ============================================================
#   Start Function (called from full_system/main.py)
# ============================================================
def run_dashboard(host=None, port=None, debug=False):
    """Start Flask dashboard (blocking - run in thread)."""
    app.run(
        host  = host  or config.FLASK_HOST,
        port  = port  or config.FLASK_PORT,
        debug = debug,
        use_reloader = False,
        threaded     = True,
    )


# ============================================================
if __name__ == "__main__":
    add_activity("CareMate Dashboard started")
    add_activity("System initialized")
    run_dashboard()
