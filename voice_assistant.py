"""
============================================================
  CareMate - Module 04: Bilingual Voice Assistant
  ============================================================
  Supports Malayalam and English voice commands.

  Pipeline:
    1. Listen via microphone (SpeechRecognition)
    2. Try recognizing in Malayalam (ml-IN), fall back to English (en-IN)
    3. Send recognized text to Groq LLM (llama3) for intelligent response
    4. Convert response to speech using gTTS
    5. Play audio via pygame (or mpg321)

  Special Commands (handled locally, no LLM needed):
    "status"  / "സ്റ്റാറ്റസ്"   → Read system status
    "stop"    / "നിർത്തുക"      → Stop voice assistant
    "help"    / "സഹായം"         → List available commands
    "call"    / "വിളിക്കൂ"      → Send emergency Telegram message

  Run standalone:
    python voice_assistant.py

  Install dependencies:
    sudo apt install espeak portaudio19-dev
    pip install SpeechRecognition gTTS pygame groq --break-system-packages
============================================================
"""

import os
import sys
import time
import logging
import subprocess
import threading
import tempfile
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s [VOICE] %(message)s')
log = logging.getLogger(__name__)

try:
    import speech_recognition as sr
    from gtts import gTTS
    import pygame
except ImportError as e:
    log.error(f"Missing dependency: {e}")
    log.error("Install: pip install SpeechRecognition gTTS pygame --break-system-packages")
    sys.exit(1)

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    log.warning("Groq not installed. Using simple fallback responses.")


# ============================================================
SYSTEM_PROMPT = """You are CareMate, an AI companion for elderly people.
You speak in simple, warm, and friendly language.
Keep responses short (under 3 sentences).
When speaking Malayalam, use proper Malayalam script.
You help with: medication reminders, health questions, weather, general conversation.
If someone asks about an emergency, tell them help is being alerted.
Always be gentle, patient, and reassuring."""

LOCAL_COMMANDS = {
    "status": "All systems are functioning normally.",
    "സ്റ്റാറ്റസ്": "എല്ലാ സിസ്റ്റങ്ങളും ശരിയായി പ്രവർത്തിക്കുന്നു.",
    "stop": "__STOP__",
    "നിർത്തുക": "__STOP__",
    "help": "You can ask me anything. Say 'status' for system status, 'stop' to stop, or just talk to me!",
    "സഹായം": "നിങ്ങൾക്ക് എന്നോട് ഏതു ചോദ്യവും ചോദിക്കാം. സ്റ്റാറ്റസ്, സഹായം, അല്ലെങ്കിൽ സംഭാഷണം തുടരൂ!",
    "call caregiver": "__CALL__",
    "emergency": "__CALL__",
}


class VoiceAssistant:
    """
    Bilingual voice assistant for CareMate.
    Listens, understands, and responds in Malayalam or English.
    """

    def __init__(self, shared_state=None):
        """
        Args:
            shared_state: Optional SharedState object from full_system (for status info).
        """
        self.shared_state  = shared_state
        self.running       = False
        self.recognizer    = sr.Recognizer()
        self.groq_client   = None
        self.conversation  = []   # Multi-turn conversation history

        # Init pygame for audio playback
        try:
            pygame.mixer.init()
        except Exception as e:
            log.warning(f"pygame mixer init failed: {e}. Will use mpg321 fallback.")

        # Init Groq
        if GROQ_AVAILABLE and config.GROQ_API_KEY != "YOUR_GROQ_API_KEY_HERE":
            self.groq_client = Groq(api_key=config.GROQ_API_KEY)
            log.info("Groq LLM connected.")
        else:
            log.warning("Groq API key not set. Using rule-based fallback responses.")

    # ----------------------------------------------------------
    def start(self):
        """Calibrate mic and begin listening loop."""
        log.info("Calibrating microphone for ambient noise...")
        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
        log.info("Microphone ready.")

        self.speak("CareMate voice assistant is ready.")
        self.running = True
        log.info("Voice assistant started. Say something!")

        self._loop()

    # ----------------------------------------------------------
    def _loop(self):
        """Main listen → understand → respond loop."""
        try:
            while self.running:
                text = self._listen()
                if text:
                    log.info(f"You said: {text}")
                    response = self._process(text)
                    if response == "__STOP__":
                        self.speak("Stopping voice assistant. Take care.")
                        break
                    elif response == "__CALL__":
                        self._emergency_call()
                    elif response:
                        self.speak(response)
        except KeyboardInterrupt:
            log.info("Interrupted.")
        finally:
            log.info("Voice assistant stopped.")

    # ----------------------------------------------------------
    def _listen(self):
        """
        Listen via microphone and return recognized text.
        Tries Malayalam first, then English.
        Returns None on failure.
        """
        with sr.Microphone() as source:
            log.info("Listening...")
            try:
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=8)
            except sr.WaitTimeoutError:
                return None

        # Try Malayalam
        try:
            text = self.recognizer.recognize_google(audio, language="ml-IN")
            log.info(f"Recognized (Malayalam): {text}")
            return text
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            log.error(f"Google Speech API error: {e}")
            return None

        # Fall back to English
        try:
            text = self.recognizer.recognize_google(audio, language="en-IN")
            log.info(f"Recognized (English): {text}")
            return text
        except sr.UnknownValueError:
            log.info("Speech not understood.")
            return None
        except sr.RequestError as e:
            log.error(f"Google Speech API error: {e}")
            return None

    # ----------------------------------------------------------
    def _process(self, text):
        """
        Determine response to user's text.
        1. Check local commands first (no network needed).
        2. Get LLM response if Groq is available.
        3. Fall back to simple rule-based reply.
        """
        text_lower = text.lower().strip()

        # Check local commands
        for keyword, response in LOCAL_COMMANDS.items():
            if keyword in text_lower:
                if response == "__STOP__":
                    return "__STOP__"
                if response == "__CALL__":
                    return "__CALL__"
                # Status command: enrich with live data
                if keyword in ("status", "സ്റ്റാറ്റസ്") and self.shared_state:
                    return self._build_status_response()
                return response

        # LLM response
        if self.groq_client:
            return self._llm_response(text)

        # Simple fallback
        return self._fallback_response(text_lower)

    # ----------------------------------------------------------
    def _llm_response(self, user_text):
        """Get response from Groq LLM."""
        self.conversation.append({"role": "user", "content": user_text})
        # Keep conversation to last 10 turns
        if len(self.conversation) > 20:
            self.conversation = self.conversation[-20:]

        try:
            resp = self.groq_client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.conversation,
                max_tokens=150,
                temperature=0.7,
            )
            reply = resp.choices[0].message.content.strip()
            self.conversation.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            log.error(f"Groq API error: {e}")
            return "Sorry, I am having trouble thinking right now. Please try again."

    # ----------------------------------------------------------
    def _fallback_response(self, text):
        """Simple rule-based fallback when Groq is not available."""
        if "hello" in text or "hi" in text or "ഹലോ" in text:
            return "Hello! I am CareMate. How can I help you today?"
        if "medicine" in text or "tablet" in text or "മരുന്ന്" in text:
            return "It is important to take your medicine on time. Please check with your doctor for dosage."
        if "water" in text or "thirsty" in text or "ദാഹം" in text:
            return "Please drink some water. Staying hydrated is very important!"
        if "pain" in text or "hurt" in text or "വേദന" in text:
            return "I am alerting your caregiver now. Please stay calm."
        if "weather" in text or "rain" in text:
            return "I am not connected to weather services right now. Please check outside!"
        return "I heard you. How can I help you further?"

    # ----------------------------------------------------------
    def _build_status_response(self):
        """Build status response using shared state data."""
        if not self.shared_state:
            return "All systems are functioning normally."
        data = self.shared_state.get_health()
        hr   = data.get("hr", 0)
        temp = data.get("temp", 0.0)
        return (f"System is active. Your heart rate is {hr} beats per minute "
                f"and body temperature is {temp} degrees Celsius.")

    # ----------------------------------------------------------
    def _emergency_call(self):
        """Send emergency alert to caregiver."""
        token   = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
        ts      = time.strftime("%Y-%m-%d %H:%M:%S")

        if token != "YOUR_BOT_TOKEN_HERE":
            msg = f"🆘 EMERGENCY CALL\nTime: {ts}\nElderly person has requested help via voice command."
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            try:
                requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=8)
                log.info("Emergency call alert sent.")
            except Exception as e:
                log.error(f"Emergency Telegram failed: {e}")

        self.speak("I am alerting your caregiver immediately. Please stay calm. Help is on the way.")

    # ----------------------------------------------------------
    def speak(self, text, lang=None):
        """
        Convert text to speech and play it.
        Auto-detects language based on script.
        """
        if lang is None:
            lang = "ml" if self._is_malayalam(text) else "en"

        log.info(f"CareMate: {text}")

        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tmp_path = config.AUDIO_OUTPUT_FILE
            tts.save(tmp_path)
            self._play_audio(tmp_path)
        except Exception as e:
            log.error(f"gTTS error: {e}. Falling back to espeak.")
            self._espeak(text)

    # ----------------------------------------------------------
    def _play_audio(self, path):
        """Play audio file using pygame."""
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        except Exception:
            # Fallback: mpg321
            try:
                subprocess.run(["mpg321", "-q", path],
                               check=True, timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                log.error(f"Audio playback failed: {e}")

    # ----------------------------------------------------------
    @staticmethod
    def _espeak(text):
        """Fallback TTS using espeak."""
        try:
            subprocess.run(["espeak", "-s", "130", text],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            pass

    # ----------------------------------------------------------
    @staticmethod
    def _is_malayalam(text):
        """Check if text contains Malayalam Unicode characters."""
        for ch in text:
            if '\u0D00' <= ch <= '\u0D7F':
                return True
        return False

    # ----------------------------------------------------------
    def process_text(self, text):
        """External entry point for full_system integration."""
        return self._process(text)

    # ----------------------------------------------------------
    def stop(self):
        self.running = False


# ============================================================
if __name__ == "__main__":
    assistant = VoiceAssistant()
    assistant.start()
