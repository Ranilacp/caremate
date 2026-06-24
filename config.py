# ============================================================
#   CareMate - Central Configuration File
#   Edit this file before running any module
# ============================================================

# --- Telegram Bot Settings ---
TELEGRAM_BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"   # Get from @BotFather
TELEGRAM_CHAT_ID    = "7343807502"             # Your caregiver chat ID

# --- Arduino / Serial Settings ---
SERIAL_PORT         = "/dev/ttyACM0"           # Use /dev/ttyUSB0 if ACM0 not found
BAUD_RATE           = 9600
SERIAL_TIMEOUT      = 2                        # seconds

# --- Camera Settings ---
CAMERA_INDEX        = 0                        # 0 = default USB webcam
FRAME_WIDTH         = 640
FRAME_HEIGHT        = 480
SHOW_PREVIEW        = False                    # Set True only if monitor is attached

# --- YOLOv8 Settings ---
YOLO_DETECT_MODEL   = "yolov8n.pt"            # Auto-downloads if not present
YOLO_POSE_MODEL     = "yolov8n-pose.pt"       # For fall detection
CONFIDENCE          = 0.45
MIN_BOX_WIDTH       = 60                       # Ignore boxes smaller than this (px)
MIN_BOX_HEIGHT      = 80

# --- Person Following Thresholds ---
DEAD_ZONE_RATIO     = 0.15                    # Centre zone as fraction of frame width
CLOSE_ZONE_RATIO    = 0.55                    # If box height > 55% of frame → STOP
FAR_ZONE_RATIO      = 0.18                    # If box height < 18% of frame → FORWARD
MOTOR_COMMAND_DELAY = 0.05                    # Seconds between serial writes

# --- Fall Detection Thresholds ---
FALL_ASPECT_RATIO   = 1.2                     # width/height > this → fallen candidate
FALL_CONFIRM_FRAMES = 4                       # Consecutive frames to confirm fall
FALL_COOLDOWN_SEC   = 15                      # Min seconds between two fall alerts
FALL_SNAPSHOT_PATH  = "/tmp/fall_snapshot.jpg"

# --- Health Monitoring Thresholds ---
HR_LOW              = 50    # BPM - Alert if below
HR_HIGH             = 110   # BPM - Alert if above
TEMP_LOW            = 35.0  # °C  - Alert if below
TEMP_HIGH           = 38.5  # °C  - Alert if above

# --- Voice Assistant Settings ---
GROQ_API_KEY        = "YOUR_GROQ_API_KEY_HERE"   # Get from console.groq.com
GROQ_MODEL          = "llama3-8b-8192"
VOICE_LANGUAGE      = "ml"                        # 'ml' Malayalam, 'en' English
AUDIO_OUTPUT_FILE   = "/tmp/caremate_response.mp3"

# --- Flask Dashboard ---
FLASK_HOST          = "0.0.0.0"
FLASK_PORT          = 5000
SECRET_KEY          = "caremate_secret_2024"

# --- Logging ---
LOG_DIR             = "/home/pi/caremate_logs"
LOG_LEVEL           = "INFO"
