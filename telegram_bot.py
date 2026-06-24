"""
============================================================
  CareMate - Telegram Alert Utility
  ============================================================
  Standalone functions for sending Telegram alerts.
  Used by both fall_detection.py and health_monitor.py.

  Usage:
    from telegram_bot import send_photo_alert, send_text_alert
    send_text_alert("System started.")
    send_photo_alert("/tmp/fall.jpg", "Fall detected at 10:30 AM")
============================================================
"""

import requests
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

log = logging.getLogger(__name__)

BASE_URL = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def _check_config():
    if config.TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        log.warning("Telegram bot token not configured in config.py")
        return False
    return True


def send_text_alert(message, chat_id=None):
    """Send a plain text message to caregiver."""
    if not _check_config():
        return False

    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    url = f"{BASE_URL}/sendMessage"

    try:
        resp = requests.post(url, json={
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "HTML"
        }, timeout=10)
        ok = resp.status_code == 200
        if ok:
            log.info("Telegram text alert sent.")
        else:
            log.error(f"Telegram error {resp.status_code}: {resp.text}")
        return ok
    except requests.exceptions.RequestException as e:
        log.error(f"Telegram request failed: {e}")
        return False


def send_photo_alert(image_path, caption="", confirm_buttons=True, chat_id=None):
    """
    Send a photo with optional inline confirmation buttons.
    Args:
        image_path:      Path to image file to send.
        caption:         Text shown below the image.
        confirm_buttons: If True, adds Confirm/False Alarm buttons.
        chat_id:         Override default chat ID.
    """
    if not _check_config():
        return False

    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    url     = f"{BASE_URL}/sendPhoto"

    params = {"chat_id": chat_id, "caption": caption}

    if confirm_buttons:
        params["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "✅ Confirm Emergency", "callback_data": "confirm_emergency"},
                {"text": "❌ False Alarm",        "callback_data": "false_alarm"}
            ]]
        }
        import json
        params["reply_markup"] = json.dumps(params["reply_markup"])

    try:
        with open(image_path, 'rb') as photo:
            resp = requests.post(url, data=params, files={"photo": photo}, timeout=15)
        ok = resp.status_code == 200
        if ok:
            log.info("Telegram photo alert sent.")
        else:
            log.error(f"Telegram photo error {resp.status_code}: {resp.text}")
        return ok
    except FileNotFoundError:
        log.error(f"Image file not found: {image_path}")
        return False
    except requests.exceptions.RequestException as e:
        log.error(f"Telegram request failed: {e}")
        return False


def send_fall_alert(snapshot_path, timestamp):
    """Convenience wrapper for fall detection alerts."""
    caption = (
        f"⚠️ FALL DETECTED\n"
        f"Time: {timestamp}\n"
        f"Awaiting caregiver confirmation"
    )
    return send_photo_alert(snapshot_path, caption, confirm_buttons=True)


def send_health_alert(hr, temp, hr_alert, temp_alert, timestamp):
    """Convenience wrapper for health monitoring alerts."""
    icons = "⚠️" * (int(hr_alert) + int(temp_alert))
    msg = f"{icons} HEALTH ALERT\nTime: {timestamp}\n"
    if hr_alert:
        msg += f"❤️ Heart Rate: {hr} BPM (Normal: {config.HR_LOW}–{config.HR_HIGH})\n"
    if temp_alert:
        msg += f"🌡️ Temperature: {temp}°C (Normal: {config.TEMP_LOW}–{config.TEMP_HIGH})\n"
    return send_text_alert(msg)


def send_system_start():
    """Notify caregiver that CareMate system has started."""
    import time
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = f"🤖 CareMate system started at {ts}.\nMonitoring is active."
    return send_text_alert(msg)


# ============================================================
if __name__ == "__main__":
    # Quick test
    print("Testing Telegram connection...")
    ok = send_text_alert("🧪 CareMate Telegram test message. System is working!")
    print(f"Result: {'✅ Sent' if ok else '❌ Failed'}")
