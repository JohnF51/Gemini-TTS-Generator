import sys
import os
import tempfile
import struct
import re
import io
import shutil
import json
import time
import math
# --- BUG FIX: Initialize global variable before try/except ---
_stanza_pipeline = None

# Imports for Sentence Splitting (Stanza)
try:
    import stanza
    # Stanza will be initialized on first call
except ImportError:
    print("Warning: The 'stanza' library was not found. Simple sentence segmentation will be used. We recommend installing it (pip install stanza).")
    stanza = None

# Import for MP3 saving (pydub)
try:
    from pydub import AudioSegment
except ImportError:
    print("Warning: The 'pydub' library was not found. Saving to MP3 might not work. We recommend installing it (pip install pydub).")
    AudioSegment = None

# --- NOVÝ IMPORT ---
from threading import Thread

# --- NEW: Define application root and subdirectories ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(APP_ROOT, "project")
TEMP_DIR = os.path.join(APP_ROOT, "temp")
VOICES_DIR = os.path.join(APP_ROOT, "voices")

import ctypes
import ctypes.wintypes
import base64

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]

def encrypt_api_key(data: str) -> str:
    """Encrypts text using Windows DPAPI bound to the user."""
    try:
        crypt32 = ctypes.windll.crypt32
        data_bytes = data.encode('utf-8')
        data_in = DATA_BLOB(len(data_bytes), ctypes.cast(data_bytes, ctypes.POINTER(ctypes.c_char)))
        data_out = DATA_BLOB()
        
        if crypt32.CryptProtectData(ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)):
            result = ctypes.string_at(data_out.pbData, data_out.cbData)
            ctypes.windll.kernel32.LocalFree(data_out.pbData)
            return base64.b64encode(result).decode('utf-8')
        return ""
    except Exception:
        return ""

def decrypt_api_key(enc_data_b64: str) -> str:
    """Decrypts text using Windows DPAPI."""
    try:
        crypt32 = ctypes.windll.crypt32
        enc_data = base64.b64decode(enc_data_b64)
        data_in = DATA_BLOB(len(enc_data), ctypes.cast(enc_data, ctypes.POINTER(ctypes.c_char)))
        data_out = DATA_BLOB()
        
        if crypt32.CryptUnprotectData(ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)):
            result = ctypes.string_at(data_out.pbData, data_out.cbData)
            ctypes.windll.kernel32.LocalFree(data_out.pbData)
            return result.decode('utf-8')
        return ""
    except Exception:
        return ""

# Global variable for API key, loaded later in TTS_App
GEMINI_API_KEY = ""

# --- NEW: Ensure directories exist on startup ---
os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(VOICES_DIR, exist_ok=True)

# Importy pre vizualizáciu
import numpy as np
import matplotlib.pyplot as plt
from PyQt6.QtGui import QPixmap, QImage, QAction, QColor, QIcon, QKeySequence
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import wave

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QComboBox, QLabel, QSlider, QGridLayout,
    QFileDialog, QMessageBox, QStatusBar, QGroupBox, QScrollArea, QSizePolicy,
    QSplitter, QTabWidget, QMenu, QInputDialog, QCheckBox, QLineEdit,
    QDialog, QPlainTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl, QSize, QMutex, QWaitCondition
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

class LogStream(QObject):
    new_text = pyqtSignal(str)

    def __init__(self, original_stream=None):
        super().__init__()
        self.original_stream = original_stream
        self.buffer = []

    def write(self, text):
        if self.original_stream:
            self.original_stream.write(text)
        self.buffer.append(text)
        if len(self.buffer) > 10000:
            self.buffer.pop(0)
        self.new_text.emit(str(text))

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()
            
    def get_logs(self):
        return "".join(self.buffer)

# Global redirection streams
LOG_STREAM = LogStream(sys.stdout)
sys.stdout = LOG_STREAM

LOG_STREAM_ERR = LogStream(sys.stderr)
sys.stderr = LOG_STREAM_ERR


class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Log Viewer")
        self.resize(750, 500)
        self.setMinimumSize(500, 350)
        
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
            }
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #dcdcdc;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #f0f0f0;
                border: 1px solid #5a5a5a;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
                border: 1px solid #0095ff;
            }
            QCheckBox {
                color: #f0f0f0;
                font-size: 10pt;
            }
        """)

        layout = QVBoxLayout(self)
        
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)
        
        controls = QHBoxLayout()
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.log_display.clear)
        
        self.save_btn = QPushButton("Save to File...")
        self.save_btn.clicked.connect(self.save_log_to_file)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        
        controls.addWidget(self.auto_scroll_cb)
        controls.addStretch()
        controls.addWidget(self.clear_btn)
        controls.addWidget(self.save_btn)
        controls.addWidget(self.close_btn)
        
        layout.addLayout(controls)

        # Load existing logs
        self.log_display.setPlainText(LOG_STREAM.get_logs())
        
        # Connect new text signals
        LOG_STREAM.new_text.connect(self.append_log)
        LOG_STREAM_ERR.new_text.connect(self.append_log)

    def append_log(self, text):
        self.log_display.insertPlainText(text)
        if self.auto_scroll_cb.isChecked():
            self.log_display.ensureCursorVisible()

    def save_log_to_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log", "gemini_tts.log", "Log Files (*.log);;Text Files (*.txt)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.log_display.toPlainText())
                QMessageBox.information(self, "Success", f"Log saved successfully to:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save log file: {e}")

# Importy pre Google Gemini
from google import genai
from google.genai import types
from google.genai.errors import APIError as GeminiAPIError

# ODSTRÁNENÉ: Importy pre sťahovanie ukážky (už nie sú potrebné)
# from urllib.request import urlopen, Request
# from urllib.error import URLError

# NOVÁ KONŠTANTA: Dostupné Markup Tagy (podľa dokumentácie)
MARKUP_TAGS = {
    "Non-Speech (Pauses)": {
        "[sigh]": "Inserts sigh",
        "[laughing]": "Inserts laughing",
        "[uhm]": "Inserts hesitation ('uhm')",
    },
    "Style and Volume": {
        "[sarcasm]": "Sarcastic tone",
        "[robotic]": "Robotic voice",
        "[shouting]": "Increases volume",
        "[whispering]": "Decreases volume (whisper)",
        "[extremely fast]": "Extremely fast speech",
    },
    "Emotion (Vocalized)": {
        "[scared]": "Scared tone (says 'scared')",
        "[curious]": "Curious tone (says 'curious')",
        "[bored]": "Bored tone (says 'bored')",
    },
    "Rhythm and Pauses": {
        "[short pause]": "~250ms pause",
        "[medium pause]": "~500ms pause",
        "[long pause]": "~1000ms+ pause",
    },
}

# NEW CONSTANT: Predefined Style Prompts (Name in UI -> EN prompt)
STYLE_PROMPT_OPTIONS = {
    "Neutral / Default style": "",
    "Calm and Authoritative tone": "Speak in a calm and authoritative tone.",
    "Friendly and Amused tone": "Say the following in a friendly and amused way.",
    "Serious and Reflective tone": "Narrate this in a serious and reflective tone.",
    "Excitement and Energy (Commercial)": "Deliver this with a high level of excitement and energy.",
    "Professional Customer Service": "Adopt a professional and neutral customer service tone.",
    "Experienced Podcast Host": "You are a confident, experienced podcast host.",
    "Old-fashioned Radio Announcer": "Speak like an old-fashioned 1940s radio news announcer.",
}


# --- ENHANCED: Expanded list of voices with gender info ---
GEMINI_VOICE_INFO = {
    "Achernar": "Female", "Achird": "Male", "Algenib": "Male", "Algieba": "Male",
    "Alnilam": "Male", "Aoede": "Female", "Autonoe": "Female", "Callirrhoe": "Female",
    "Charon": "Male", "Despina": "Female", "Enceladus": "Male", "Erinome": "Female",
    "Fenrir": "Male", "Gacrux": "Female", "Iapetus": "Male", "Kore": "Female",
    "Laomedeia": "Female", "Leda": "Female", "Orus": "Male", "Pulcherrima": "Female",
    "Puck": "Male", "Rasalgethi": "Male", "Sadachbia": "Male", "Sadaltager": "Male",
    "Schedar": "Male", "Sulafat": "Female", "Umbriel": "Male", "Vindemiatrix": "Female",
    "Zephyr": "Female", "Zubenelgenubi": "Male"
}
GEMINI_VOICES = list(GEMINI_VOICE_INFO.keys())


# Dynamic voice preview will be cached per voice to avoid repeated API calls


# NEW CONSTANT: Available Gemini TTS models
GEMINI_TTS_MODELS = {
    "Gemini 2.5 Pro TTS (Highest quality, style control)": "gemini-2.5-pro-preview-tts",
    "Gemini 2.5 Flash TTS (Lower latency)": "gemini-2.5-flash-preview-tts"
}

# NEW CONSTANT: Supported languages (Name in UI -> Code for API)
SUPPORTED_LANGUAGES = {
    "Slovak (SK)": "sk-SK",
    "Czech (CZ)": "cs-CZ",
    "English (US)": "en-US",
    "English (GB)": "en-GB",
    "German (DE)": "de-DE",
    "Spanish (ES)": "es-ES",
    "French (FR)": "fr-FR",
}

# --- MODIFIED Temporary File Manager ---
class TempFileManager:
    """Manages the temporary /temp directory for WAV and PNG files and handles its cleanup."""
    def __init__(self):
        # --- CHANGE: Uses predefined TEMP_DIR directory ---
        self.temp_dir = TEMP_DIR
        print(f"Using temporary directory: {self.temp_dir}")
        self._temp_files = set() # Set of paths to temporary files

    def create_temp_file(self, suffix: str, data: bytes = None) -> str:
        """Creates a temporary file in the managed directory and returns its path."""
        # Using os.path.join for cross-platform compatibility
        temp_file_path = os.path.join(self.temp_dir, next(tempfile._get_candidate_names()) + suffix)
        if data:
            with open(temp_file_path, "wb") as f:
                f.write(data)
        self._temp_files.add(temp_file_path)
        return temp_file_path

    def cleanup(self):
        """Deletes the contents of the temporary directory but keeps the directory itself."""
        try:
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        print(f"Error deleting file {file_path}: {e}")
                print(f"Temporary directory contents cleared: {self.temp_dir}")
            self._temp_files.clear()
        except Exception as e:
            print(f"Error clearing temporary directory {self.temp_dir}: {e}")

# --- Pomocné funkcie pre konverziu audio dát z Gemini ---

def parse_audio_mime_type(mime_type: str) -> dict[str, int | None]:
    """Parse bity na vzorku a rýchlosť zo stringu MIME typu pre audio."""
    bits_per_sample = 16
    rate = 24000

    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass

    return {"bits_per_sample": bits_per_sample, "rate": rate}

def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generuje WAV hlavičku pre surové audio dáta (L16) z Gemini a vráti kompletný WAV súbor."""
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",          # ChunkID
        chunk_size,       # ChunkSize
        b"WAVE",          # Format
        b"fmt ",          # Subchunk1ID
        16,               # Subchunk1Size
        1,                # AudioFormat (PCM)
        num_channels,     # NumChannels
        sample_rate,      # SampleRate
        byte_rate,        # ByteRate
        block_align,      # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",          # Subchunk2ID
        data_size         # Subchunk2Size
    )
    return header + audio_data

# --- FUNKCIE PRE ROZDELenie TEXTU ---

def _init_stanza(lang: str = 'cs'):
    """
    Inicializuje Stanza pipeline, ak je k dispozícii a ešte nebola.
    """
    global _stanza_pipeline

    if stanza and _stanza_pipeline is None:
        try:
            print(f"Checking/loading Stanza model for '{lang}' to default directory (tokenization only)...")
            stanza.download(lang=lang, processors='tokenize', verbose=False)
            _stanza_pipeline = stanza.Pipeline(lang=lang, processors='tokenize', verbose=False)
            print("Stanza pipeline successfully initialized.")

        except Exception as e:
            print(f"Error initializing Stanza pipeline for '{lang}', switching to fallback: {e}")
            _stanza_pipeline = False

    if _stanza_pipeline is False:
        return False

    return _stanza_pipeline

def _split_text_simple_fallback(text: str, sentences_per_segment: int = 3) -> list[str]:
    """Fallback simple heuristic to split sentences."""
    text = re.sub(r'([.!?])(?=\s*\S|$)', r'\1 ', text)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
         sentences = [s.strip() for s in text.splitlines() if s.strip()]

    segments = []
    current_segment = []
    for i, sentence in enumerate(sentences):
        current_segment.append(sentence)
        if len(current_segment) == sentences_per_segment or i == len(sentences) - 1:
            segments.append(" ".join(current_segment))
            current_segment = []

    return [s.strip() for s in segments if s.strip()]


def _split_text_into_segments(text: str, sentences_per_segment: int = 3) -> list[str]:
    """
    Splits text into segments of N sentences using smarter sentence segmentation (Stanza).
    """
    sentences = []
    stanza_pipe = _init_stanza('cs')

    if stanza_pipe:
        try:
            doc = stanza_pipe(text)
            sentences = [sentence.text.strip() for sentence in doc.sentences if sentence.text.strip()]
        except Exception as e:
            print(f"Error processing text via Stanza, switching to fallback: {e}")
            return _split_text_simple_fallback(text, sentences_per_segment)
    else:
        return _split_text_simple_fallback(text, sentences_per_segment)

    if not sentences:
        return _split_text_simple_fallback(text, sentences_per_segment)

    segments = []
    current_segment = []
    for i, sentence in enumerate(sentences):
        current_segment.append(sentence)
        if len(current_segment) == sentences_per_segment or i == len(sentences) - 1:
            segments.append(" ".join(current_segment))
            current_segment = []

    return [s.strip() for s in segments if s.strip()]

# --- FUNCTION FOR WAV VISUALIZATION ---

def create_waveform_png_data(audio_data: bytes, width: int = 400, height: int = 50) -> bytes:
    """Renders audio data (WAV) as a waveform and returns raw PNG bytes."""

    try:
        if not audio_data:
            return b''

        wav_file = io.BytesIO(audio_data)

        with wave.open(wav_file, 'rb') as raw:
            signal = raw.readframes(-1)
            signal_array = np.frombuffer(signal, dtype=np.int16)
            f_rate = raw.getframerate()

            if len(signal_array) == 0:
                 # NEW: Render empty (silent) track
                 fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
                 ax = fig.add_subplot(111)
                 ax.plot([0, 1], [0, 0], color='#0095ff', linewidth=0.5)
            else:
                 time_arr = np.linspace(0, len(signal_array) / f_rate, num=len(signal_array))

                 # Matplotlib settings for compact PNG
                 fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
                 ax = fig.add_subplot(111)

                 # Change waveform color for dark mode
                 ax.plot(time_arr, signal_array, color='#0095ff', linewidth=0.5)

            ax.set_xticks([])
            ax.set_yticks([])
            ax.axis('off')
            ax.margins(0,0)

            # Set transparent background for fig and ax
            fig.patch.set_alpha(0.0)
            ax.patch.set_alpha(0.0)

            plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

            # Save to memory (BytesIO)
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
            buf.seek(0)

            plt.close(fig)

            return buf.read()

    except Exception as e:
        print(f"Error generating waveform: {e}")
        return b''

# REMOVED WORKER: PreviewDownloader was replaced by local playback ---

# --- Worker class for Gemini ---

class GeminiWorker: # <-- CHANGE: No longer inherits from QObject
    """Worker for Gemini TTS (streamed audio), ONLY Single-Speaker."""
    
    def __init__(self, params, signals): # <-- CHANGE: Added 'signals' parameter
        super().__init__()
        self.params = params
        self.signals = signals # <-- CHANGE: Store signals
        self.text = self.params["text"]
        self.prompt = self.params.get("prompt", "")
        self.voice_name = self.params.get("voice_name", "Zephyr")
        self.temperature = self.params.get("temperature", 1.0)
        self.model = self.params.get("model", "gemini-2.5-pro-preview-tts")
        # NEW: Load language and speed
        self.language_code = self.params.get("language_code", "sk-SK")
        self.speaking_rate = self.params.get("speaking_rate", 1.0)
        self.client = None

    def run(self):
        try:
            # --- ADDED LOGGING ---
            print(f"\n[INFO] Starting GeminiWorker for text: '{self.text[:50]}...'")
            print(f"[INFO] Used model: {self.model}, Voice: {self.voice_name}, Language: {self.language_code}")
            print("---DEBUG: Step 1 - Creating client...")
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            # --- ADDED LOGGING ---
            print("[INFO] Client for Gemini API was successfully initialized.")
            print("---DEBUG: Step 2 - Client created, preparing data...")
            
            # Detailed request logging
            print(f"[API REQUEST] Sending TTS Request to model: '{self.model}'")
            print(f"              Voice Name: '{self.voice_name}'")
            print(f"              Language Code: '{self.language_code}'")
            print(f"              Speaking Rate: {self.speaking_rate}x")
            print(f"              Temperature: {self.temperature}")
            print(f"              Style Prompt: '{self.prompt}'")
            print(f"              Input Text Length: {len(self.text)} characters")
                        
            parts_list = []
            if self.prompt:
                 parts_list.append(types.Part.from_text(text=f"Prompt: {self.prompt}"))

            parts_list.append(types.Part.from_text(text=self.text))

            contents = [
                types.Content(
                    role="user",
                    parts=parts_list,
                ),
            ]

            self.voice_name = self.voice_name if self.voice_name in GEMINI_VOICES else "Algieba"
            
            speech_config_params = {
                "voice_config": types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                ),
                "language_code": self.language_code,
            }

            generate_content_config = types.GenerateContentConfig(
                temperature=self.temperature,
                response_modalities=["audio"],
                speech_config=types.SpeechConfig(**speech_config_params),
            )
            
            request_options = {
                "speech_options": {
                    "speaking_rate": self.speaking_rate
                }
            }
            
            full_audio_data = b""
            mime_type = ""
            in_tokens = 0
            out_tokens = 0

            # --- ADDED LOGGING ---
            print("[INFO] Sending request to Gemini API and waiting for streamed data...")
            start_time = time.time()

            print("---DEBUG: Step 3 - Attempting to connect to API and stream data...")
            chunk_count = 0
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
                #request_options=request_options
            ):
                chunk_count += 1
                chunk_size = 0
                
                if (
                    chunk.candidates
                    and chunk.candidates[0].content
                    and chunk.candidates[0].content.parts
                    and chunk.candidates[0].content.parts[0].inline_data
                    and chunk.candidates[0].content.parts[0].inline_data.data
                ):
                    inline_data = chunk.candidates[0].content.parts[0].inline_data
                    chunk_size = len(inline_data.data)
                    full_audio_data += inline_data.data
                    if not mime_type:
                        mime_type = inline_data.mime_type

                # --- ADDED LOGGING ---
                if not full_audio_data: # Printed only when first chunk is received
                    first_chunk_time = time.time()
                    print(f"[INFO] First chunk of data received after {first_chunk_time - start_time:.2f} seconds.")

                print(f"[API RESPONSE] Received stream chunk #{chunk_count}: {chunk_size} bytes. (Total accumulated: {len(full_audio_data)} bytes)")

                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    in_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', in_tokens) or in_tokens
                    out_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', out_tokens) or out_tokens

            # --- ADDED LOGGING ---
            end_time = time.time()
            print(f"[INFO] Streaming complete. Total time: {end_time - start_time:.2f} seconds.")
            print(f"[INFO] Total size of received audio data: {len(full_audio_data)} bytes.")
            print(f"[API INFO] Usage Metadata - Input tokens: {in_tokens}, Output tokens: {out_tokens}")

            if not full_audio_data:
                 print("[ERROR] Generation returned no audio data.")
                 self.signals.error.emit(f"Gemini TTS generation returned no audio data. Model used: {self.model}")
                 return

            if not mime_type.lower().startswith("audio/wav"):
                # --- ADDED LOGGING ---
                print(f"[INFO] Received MIME type '{mime_type}', converting to WAV.")
                full_audio_data = convert_to_wav(full_audio_data, mime_type)
                final_mime_type = "audio/wav"
                print("[INFO] Conversion to WAV complete.")
            else:
                final_mime_type = mime_type

            result = {
                "audio_content": full_audio_data,
                "mime_type": final_mime_type,
                "char_count": len(self.text),
                "model_used": self.model,
                "in_tokens": in_tokens,
                "out_tokens": out_tokens
            }
            # --- ADDED LOGGING ---
            print("[SUCCESS] Worker successfully completed work.")
            self.signals.finished.emit(result)

        except GeminiAPIError as e:
             # --- ADDED LOGGING ---
             print(f"[FATAL ERROR] Error calling Gemini API: {e}")
             self.signals.error.emit(f"Error calling Gemini API: {e}. Make sure the API key is valid and permissions are active.")
        except ValueError as e:
            # --- ADDED LOGGING ---
            print(f"[FATAL ERROR] Gemini configuration error: {e}")
            self.signals.error.emit(f"Gemini configuration error: {e}")
        except Exception as e:
            # --- ADDED LOGGING ---
            print(f"[FATAL ERROR] Unknown error in GeminiWorker: {e}")
            self.signals.error.emit(f"Unknown error (Gemini TTS): {e}")

# --- Worker class for BATCH GENERATION ---

class SegmentBatchWorker(QObject):
    """Worker that sequentially generates segments."""

    segment_generated = pyqtSignal(int, object)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, segments_to_process: list[dict], prompt: str, temperature: float, model: str, temp_file_manager: TempFileManager, language_code: str, speaking_rate: float):
        super().__init__()
        self.segments_to_process = segments_to_process
        self.prompt = prompt
        self.temperature = temperature
        self.model = model
        self.temp_file_manager = temp_file_manager
        # NEW: Store language and speed
        self.language_code = language_code
        self.speaking_rate = speaking_rate
        self._is_cancelled = False

    def cancel(self):
        """Cancels the current batch operation."""
        self._is_cancelled = True

    def run(self):
        try:
            print("[INFO] Starting SegmentBatchWorker batch generation.")
            client = genai.Client(api_key=GEMINI_API_KEY)
            print("[INFO] Client for Gemini API was successfully initialized.")
            i = -1 # For error handling before loop

            for i, segment_info in enumerate(self.segments_to_process):
                if self._is_cancelled:
                    self.status_update.emit(f"Batch generation canceled by user (Segment {i+1}/{len(self.segments_to_process)}).")
                    print(f"[INFO] Batch generation canceled by user at segment {i+1}.")
                    break
                
                text = segment_info["text"]
                voice_name = segment_info["voice"] # --- ENHANCED: Voice for each segment ---

                self.status_update.emit(f"Generating speech (Segment {i+1}/{len(self.segments_to_process)}), please wait...")
                print(f"\n[INFO] Batch processing - Starting segment {i+1}/{len(self.segments_to_process)}")
                
                # Detailed request logging
                print(f"[API REQUEST] Sending Batch TTS Request for segment {i+1}")
                print(f"              Model: '{self.model}'")
                print(f"              Voice Name: '{voice_name}'")
                print(f"              Language Code: '{self.language_code}'")
                print(f"              Speaking Rate: {self.speaking_rate}x")
                print(f"              Temperature: {self.temperature}")
                print(f"              Style Prompt: '{self.prompt}'")
                print(f"              Input Text Length: {len(text)} characters")

                parts_list = []
                if self.prompt:
                    parts_list.append(types.Part.from_text(text=f"Prompt: {self.prompt}"))

                parts_list.append(types.Part.from_text(text=text))

                contents = [
                    types.Content(
                        role="user",
                        parts=parts_list,
                    ),
                ]

                voice_name = voice_name if voice_name in GEMINI_VOICES else "Algieba"
                
                # MODIFIED: Added language and speed to the configuration
                speech_config_params = {
                    "voice_config": types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    ),
                    "language_code": self.language_code,
                    
                }

                generate_content_config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    response_modalities=["audio"],
                    speech_config=types.SpeechConfig(**speech_config_params),
                )
                
                request_options = {
                    "speech_options": {
                        "speaking_rate": self.speaking_rate
                    }
                }
                
                full_audio_data = b""
                mime_type = ""
                in_tokens = 0
                out_tokens = 0

                print(f"[INFO] Sending request to Gemini API for segment {i+1}...")
                start_time = time.time()
                
                chunk_count = 0
                for chunk in client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=generate_content_config,
                    #request_options=request_options
                ):
                    if self._is_cancelled:
                        self.status_update.emit(f"Batch generation canceled (Segment {i+1}).")
                        print(f"[INFO] Batch generation canceled at segment {i+1} mid-stream.")
                        return

                    chunk_count += 1
                    chunk_size = 0
                    if (
                        chunk.candidates
                        and chunk.candidates[0].content
                        and chunk.candidates[0].content.parts
                        and chunk.candidates[0].content.parts[0].inline_data
                        and chunk.candidates[0].content.parts[0].inline_data.data
                    ):
                        inline_data = chunk.candidates[0].content.parts[0].inline_data
                        chunk_size = len(inline_data.data)
                        full_audio_data += inline_data.data
                        if not mime_type:
                            mime_type = inline_data.mime_type

                    if not full_audio_data: # Printed only when first chunk is received
                        first_chunk_time = time.time()
                        print(f"[INFO] First chunk of data received for segment {i+1} after {first_chunk_time - start_time:.2f} seconds.")

                    print(f"[API RESPONSE] Segment {i+1} - Received stream chunk #{chunk_count}: {chunk_size} bytes. (Total accumulated: {len(full_audio_data)} bytes)")

                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        in_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', in_tokens) or in_tokens
                        out_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', out_tokens) or out_tokens

                if not full_audio_data:
                    raise Exception(f"Generation of segment {i+1} returned no audio data.")

                end_time = time.time()
                print(f"[INFO] Segment {i+1} streaming complete. Total time: {end_time - start_time:.2f} seconds.")
                print(f"[INFO] Segment {i+1} total audio size: {len(full_audio_data)} bytes.")
                print(f"[API INFO] Segment {i+1} usage metadata - Input tokens: {in_tokens}, Output tokens: {out_tokens}")

                if not mime_type.lower().startswith("audio/wav"):
                    print(f"[INFO] Segment {i+1} received MIME type '{mime_type}', converting to WAV...")
                    audio_content = convert_to_wav(full_audio_data, mime_type)
                    print(f"[INFO] Segment {i+1} conversion to WAV complete.")
                else:
                    audio_content = full_audio_data

                audio_path = self.temp_file_manager.create_temp_file(".wav", audio_content)
                png_data = create_waveform_png_data(audio_content, width=800, height=70)
                png_path = self.temp_file_manager.create_temp_file(".png", png_data)

                result = {
                    "audio_content": audio_content,
                    "audio_temp_path": audio_path,
                    "png_temp_path": png_path,
                    "char_count": len(text),
                    "model_used": self.model,
                    "in_tokens": in_tokens,
                    "out_tokens": out_tokens
                }
                # Return original index from `segment_data`
                print(f"[SUCCESS] Segment {i+1} generation completed.")
                self.segment_generated.emit(segment_info["original_index"], result)


            if not self._is_cancelled:
                print("[SUCCESS] Batch generation finished successfully.")
                self.finished.emit()

        except GeminiAPIError as e:
             self.error.emit(f"Error calling Gemini API in batch: {e}.")
        except Exception as e:
            segment_num_str = f" (Segment {i+1})" if i != -1 else ""
            self.error.emit(f"Unknown error in batch generation{segment_num_str}: {e}")

# --- NEW HELPER CLASS FOR SIGNALS ---
class WorkerSignals(QObject):
    """
    Defines signals available from the worker thread.
    - finished: signal upon successful completion
    - error: signal in case of error
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

# --- NEW CLASS FOR DYNAMICALLY FETCHING MODELS ---
class ModelFetchWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            if not GEMINI_API_KEY:
                self.error.emit("Missing API key.")
                return
            print("[INFO] ModelFetchWorker starting: requesting list of models from Gemini API...")
            client = genai.Client(api_key=GEMINI_API_KEY)
            tts_models = {}
            # Iterate through available models
            for m in client.models.list():
                name = m.name
                # TTS models contain 'tts'
                if "tts" in name.lower():
                    display_name = getattr(m, 'display_name', None)
                    if not display_name:
                        # If there is no display_name, use formatted name
                        display_name = name.replace("models/", "").replace("-", " ").title()
                    else:
                        pass
                    tts_models[display_name] = name.replace("models/", "")
            
            if tts_models:
                print(f"[SUCCESS] ModelFetchWorker successfully loaded {len(tts_models)} TTS models from Gemini API: {list(tts_models.values())}")
                self.finished.emit(tts_models)
            else:
                print("[ERROR] ModelFetchWorker completed, but no TTS models were found in the Gemini response.")
                self.error.emit("No TTS models found.")
        except Exception as e:
            print(f"[ERROR] ModelFetchWorker failed to fetch models from Gemini API: {e}")
            self.error.emit(str(e))


class CustomTextEdit(QTextEdit):
    """Extended QTextEdit for tracking focus (Focus In)."""
    focus_in_signal = pyqtSignal(object)

    def focusInEvent(self, event):
        """Override focus in event."""
        super().focusInEvent(event)
        self.focus_in_signal.emit(self)


class TTS_App(QMainWindow):
    def __init__(self):
        super().__init__()

        self.log_viewer = None
        print("[INFO] Application started and initialized successfully.")

        self.temp_file_manager = TempFileManager()
        self.active_text_widget = None
        self.audio_content = None
        self.full_audio_temp_path = None
        self.segment_data = []

        # --- NEW: Language and pricing configuration ---
        self.config_path = os.path.join(APP_ROOT, "settings.json")
        self.current_lang = "en"
        self.pro_rate = 0.0
        self.flash_rate = 0.0
        self.in_tokens_count = 0
        self.out_tokens_count = 0
        self.total_cost = 0.0
        self.load_settings()

        # --- ENHANCED: Character counters ---
        self.pro_char_count = 0
        self.flash_char_count = 0

        # Workers for generation
        self.current_worker = None
        self.current_thread = None
        self.batch_worker: SegmentBatchWorker | None = None
        self.batch_thread: QThread | None = None
        
        # --- ENHANCED: Tracking running generators for multitasking ---
        # CHANGE: Switching to threading.Thread, active_single_gen_threads is no longer needed
        self.active_single_gen_threads = {} # {index: Thread}

        # NEW: Tracking for dynamic voice preview generation (persistent cache in VOICES_DIR)
        self.active_preview_thread = None

        # Player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self.update_play_button_state)
        self.player.errorOccurred.connect(self.media_player_error)

        self.init_ui()
        self.populate_gemini_voices()
        self.fetch_dynamic_models()

        self.setWindowTitle("Gemini TTS Generator")
        self.setGeometry(100, 100, 1400, 900)

        self.full_waveform_label.setText("Waveform: Merge segments to view full waveform.")
        self.full_waveform_label.setPixmap(QPixmap())

        self.gemini_model_combo.setCurrentText(list(GEMINI_TTS_MODELS.keys())[0])
        self.update_char_count_labels()


    def load_settings(self):
        """Loads application settings from file."""
        global GEMINI_API_KEY
        
        # 1. First load from settings.json
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.pro_rate = config.get("pro_rate", 0.0)
                    self.flash_rate = config.get("flash_rate", 0.0)
                    enc_key = config.get("encrypted_api_key", "")
                    if enc_key:
                        decrypted = decrypt_api_key(enc_key)
                        if decrypted:
                            GEMINI_API_KEY = decrypted
            except Exception as e:
                print(f"Error loading settings: {e}")

        # 2. Migration from old gemini.txt file (if exists)
        old_key_path = os.path.join(APP_ROOT, "gemini.txt")
        if os.path.exists(old_key_path):
            try:
                with open(old_key_path, "r", encoding="utf-8") as f:
                    api_key = f.read().strip()
                if api_key:
                    GEMINI_API_KEY = api_key
                    self.save_settings() # Encrypts and saves
                    print("INFO: API key successfully migrated from gemini.txt to settings.json.")
                # Delete old unsecured file
                os.remove(old_key_path)
                print("INFO: gemini.txt file was safely removed.")
            except Exception as e:
                print(f"ERROR migrating gemini.txt: {e}")

    def save_settings(self):
        """Saves application settings to file."""
        global GEMINI_API_KEY
        try:
            config = {}
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    
            config["language"] = self.current_lang
            config["pro_rate"] = self.pro_rate
            config["flash_rate"] = self.flash_rate
            
            if GEMINI_API_KEY:
                encrypted = encrypt_api_key(GEMINI_API_KEY)
                if encrypted:
                    config["encrypted_api_key"] = encrypted

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

        # Translate menu (updates action texts)
        self.file_menu.setTitle("File")
        self.new_action.setText("New Project")
        self.open_action.setText("Load Project...")
        self.save_action.setText("Save Project...")
        self.save_audio_action.setText("Save Full WAV...")
        self.exit_action.setText("Exit")

        self.tools_menu.setTitle("Tools")
        self.clean_temp_action.setText("Clear temporary files")
        if hasattr(self, 'set_api_key_action'):
            self.set_api_key_action.setText("Set API Key...")
        if hasattr(self, 'set_pricing_action'):
            self.set_pricing_action.setText("Set Rates (Pricing)...")
        if hasattr(self, 'show_logs_action'):
            self.show_logs_action.setText("Show Logs...")
        
        self.help_menu.setTitle("Help")
        self.about_action.setText("About")

        # Update existing segments (dynamic translation of UI elements inside segments)
        for i in range(len(self.segment_data)):
            try:
                play_btn = self.segments_container.findChild(QPushButton, f"play_button_{i}")
                if play_btn:
                    if "▶" in play_btn.text(): play_btn.setText("▶ Play")
                    else: play_btn.setText("◼ Stop")
                
                gen_btn = self.segments_container.findChild(QPushButton, f"generate_button_{i}")
                if gen_btn: gen_btn.setText("🔊 Generate")
                
                silence_btn = self.segments_container.findChild(QPushButton, f"silence_button_{i}")
                if silence_btn: silence_btn.setText("🔇 Silence")
                
                del_btn = self.segments_container.findChild(QPushButton, f"delete_button_{i}")
                if del_btn: del_btn.setText("🗑 Delete")
                
                tag_btn = self.segments_container.findChild(QPushButton, f"tag_button_{i}")
                if tag_btn: tag_btn.setText("Insert Tag")
            except Exception:
                pass
                
        # Status bar update only if it is the default message
        if "ready" in self.status_bar.currentMessage().lower() or "pripravená" in self.status_bar.currentMessage().lower():
            self.status_bar.showMessage("Application ready.")

    
    def populate_gemini_voices(self):
        """Populates the ComboBox with a static list of Gemini voices with gender information."""
        self.gemini_voice_combo.clear()
        
        # --- ENHANCED: Displays name and gender ---
        for voice, gender in GEMINI_VOICE_INFO.items():
            gender_char = "M" if gender == "Male" else "F"
            self.gemini_voice_combo.addItem(f"{voice} ({gender_char})", voice)

        default_voice_name = "Algieba"
        default_voice_index = self.gemini_voice_combo.findData(default_voice_name)
        if default_voice_index != -1:
            self.gemini_voice_combo.setCurrentIndex(default_voice_index)
        elif self.gemini_voice_combo.count() > 0:
            self.gemini_voice_combo.setCurrentIndex(0)

    def fetch_dynamic_models(self):
        """Starts a thread to asynchronously load current models."""
        self.model_fetch_thread = QThread()
        self.model_fetch_worker = ModelFetchWorker()
        self.model_fetch_worker.moveToThread(self.model_fetch_thread)
        self.model_fetch_thread.started.connect(self.model_fetch_worker.run)
        self.model_fetch_worker.finished.connect(self.on_models_fetched)
        self.model_fetch_worker.error.connect(self.on_models_fetch_error)
        
        self.gemini_model_combo.setItemText(0, "Loading current models from API...")
        self.model_fetch_thread.start()

    def on_models_fetched(self, models_dict):
        global GEMINI_TTS_MODELS
        # Update default models with dynamically loaded ones
        GEMINI_TTS_MODELS.update(models_dict)
        
        current_text = self.gemini_model_combo.currentText()
        self.gemini_model_combo.clear()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        self.status_bar.showMessage("Current TTS models successfully loaded from Gemini API.")
        
        self.model_fetch_thread.quit()
        self.model_fetch_thread.wait()

    def on_models_fetch_error(self, err_msg):
        self.status_bar.showMessage("Failed to load models, using defaults. ({0})".format(err_msg))
        self.gemini_model_combo.clear()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        self.model_fetch_thread.quit()
        self.model_fetch_thread.wait()

    def set_active_text_widget(self, widget: QTextEdit):
        """Stores reference to the text box that just gained focus."""
        self.active_text_widget = widget

    def get_segment_play_button(self, index: int) -> QPushButton | None:
        """Finds segment play button by index."""
        # Check if container still exists
        if self.segments_container:
            return self.segments_container.findChild(QPushButton, f"play_button_{index}")
        return None

    def update_segment_play_button_ui(self, index: int, state):
        """Updates Play/Stop button text of a segment."""
        button = self.get_segment_play_button(index)
        if button:
             if state == QMediaPlayer.PlaybackState.PlayingState:
                 button.setText("◼ Stop")
             elif state in [QMediaPlayer.PlaybackState.StoppedState, QMediaPlayer.PlaybackState.PausedState]:
                 button.setText("▶ Play")

    def update_play_button_state(self, state):
        """Updates Play Full or segment play button texts."""
        is_playing_local_file = self.player.source().isLocalFile()

        # If not playing local file (e.g. error), reset UI
        if not is_playing_local_file:
            is_playing = state == QMediaPlayer.PlaybackState.PlayingState
            self.stop_all_button.setEnabled(is_playing)
            self.set_ui_enabled(not is_playing)
            return

        source_path = self.player.source().toLocalFile()
        is_preview = VOICES_DIR in os.path.normpath(source_path)

        # If preview is playing, only update the STOP button, keep segment buttons enabled
        if is_preview:
            is_playing = state == QMediaPlayer.PlaybackState.PlayingState
            self.stop_all_button.setEnabled(is_playing)
            return

        # Reset other segment buttons to "Play"
        for i in range(len(self.segment_data)):
            segment_path = self.segment_data[i].get("audio_temp_path")
            if segment_path and segment_path != source_path:
                self.update_segment_play_button_ui(i, QMediaPlayer.PlaybackState.StoppedState)

        # Update main player buttons
        if source_path and source_path == self.full_audio_temp_path:
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self.play_full_button.setText("◼ Stop Full")
            else:
                self.play_full_button.setText("▶ Play Full")
        else:
            self.play_full_button.setText("▶ Play Full")

        # Update currently playing segment button
        if source_path:
            for i, data in enumerate(self.segment_data):
                if data.get("audio_temp_path") == source_path:
                    self.update_segment_play_button_ui(i, state)
                    break

        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.stop_all_button.setEnabled(is_playing)

        # Do not disable UI during preview or multitasking playback
        if not (self.batch_thread and self.batch_thread.isRunning()):
            if not is_playing:
                self.set_ui_enabled(True)


    def set_dark_style(self):
        """Sets global stylesheet for dark mode and premium aesthetics."""
        dark_stylesheet = """
        QMainWindow, QWidget {
            background-color: #2e2e2e;
            color: #f0f0f0;
            font-size: 10pt;
        }
        QTabWidget::pane {
            border-top: 2px solid #5a5a5a;
        }
        QTabBar::tab {
            background: #3c3c3c;
            border: 1px solid #5a5a5a;
            border-bottom-color: #3c3c3c;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            min-width: 8ex;
            padding: 8px 15px;
            font-size: 11pt;
        }
        QTabBar::tab:selected, QTabBar::tab:hover {
            background: #5a5a5a;
        }
        QTabBar::tab:selected {
            border-color: #777;
            border-bottom-color: #5a5a5a; /* same as pane color */
            color: #0095ff;
        }
        QGroupBox {
            background-color: #3c3c3c;
            border: 1px solid #5a5a5a;
            border-radius: 5px;
            margin-top: 10px;
            padding: 15px 10px 10px 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px;
            color: #0095ff;
            font-weight: bold;
        }
        QPushButton {
            background-color: #5a5a5a;
            color: #f0f0f0;
            border: 1px solid #777;
            border-radius: 4px;
            padding: 5px;
            min-height: 25px;
        }
        QPushButton:hover {
            background-color: #6a6a6a;
        }
        QPushButton:pressed {
            background-color: #0095ff;
            border-color: #0095ff;
        }
        QPushButton:disabled {
            background-color: #4a4a4a;
            color: #999999;
        }
        QTextEdit, QComboBox, QCheckBox {
            background-color: #4a4a4a;
            color: #f0f0f0;
            border: 1px solid #5a5a5a;
            border-radius: 3px;
            padding: 2px;
        }
        QSlider::groove:horizontal {
            border: 1px solid #5a5a5a;
            background: #4a4a4a;
            height: 8px;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #0095ff;
            border: 1px solid #0095ff;
            width: 18px;
            margin: -2px 0;
            border-radius: 3px;
        }
        QStatusBar {
            background-color: #1e1e1e;
            color: #0095ff;
        }
        QScrollArea {
            border: none;
        }
        QWidget#SegmentRow {
            border: 1px solid #4a4a4a;
            border-radius: 5px;
            margin: 2px 0;
            padding: 5px;
            background-color: #353535;
        }
        QMenuBar {
             background-color: #3c3c3c;
             color: #f0f0f0;
        }
        QMenu {
             background-color: #4a4a4a;
             color: #f0f0f0;
             border: 1px solid #5a5a5a;
        }
        QMenu::item:selected {
            background-color: #0095ff;
            color: #f0f0f0;
        }
        QSplitter::handle {
            background: #5a5a5a;
        }
        """
        self.setStyleSheet(dark_stylesheet)

    def init_ui(self):
        self.set_dark_style()
        self.create_menu_bar()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- MAIN TAB WIDGET ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- TAB 1: Input & Settings ---
        self.tab1 = QWidget()
        self.tabs.addTab(self.tab1, "1. Input & Settings")
        tab1_layout = QHBoxLayout(self.tab1)

        # LEFT PANEL: Text Input
        left_panel_tab1 = QWidget()
        left_layout_tab1 = QVBoxLayout(left_panel_tab1)
        self.input_group = QGroupBox("Main Text Input")
        input_layout = QVBoxLayout(self.input_group)
        
        # Import button layout
        import_layout = QHBoxLayout()
        self.import_button = QPushButton("Import TXT")
        self.import_button.clicked.connect(self.import_txt_file)
        import_layout.addWidget(self.import_button)
        import_layout.addStretch()
        input_layout.addLayout(import_layout)

        self.text_input = CustomTextEdit()
        self.text_input.focus_in_signal.connect(self.set_active_text_widget)
        self.text_input.setPlaceholderText("Paste your text for text-to-speech here...")
        input_layout.addWidget(self.text_input)
        left_layout_tab1.addWidget(self.input_group)
        tab1_layout.addWidget(left_panel_tab1, 2) # Larger ratio

        # RIGHT PANEL: Settings & Control
        right_panel_tab1 = QWidget()
        right_layout_tab1 = QVBoxLayout(right_panel_tab1)
        right_layout_tab1.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.settings_group = QGroupBox("Default Generation Settings")
        settings_layout = QGridLayout(self.settings_group)

        self.gemini_model_combo_label = QLabel("TTS Model:")
        settings_layout.addWidget(self.gemini_model_combo_label, 0, 0)
        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        settings_layout.addWidget(self.gemini_model_combo, 0, 1, 1, 2)

        self.gemini_voice_combo_label = QLabel("Default Voice:")
        settings_layout.addWidget(self.gemini_voice_combo_label, 1, 0)
        self.gemini_voice_combo = QComboBox()
        self.voice_preview_button = QPushButton("🔊 Preview")
        self.voice_preview_button.clicked.connect(self.play_voice_preview)
        settings_layout.addWidget(self.gemini_voice_combo, 1, 1)
        settings_layout.addWidget(self.voice_preview_button, 1, 2)
        
        # NEW: Language Selection
        self.language_combo_label = QLabel("Language:")
        settings_layout.addWidget(self.language_combo_label, 2, 0)
        self.language_combo = QComboBox()
        self.language_combo.addItems(SUPPORTED_LANGUAGES.keys())
        self.language_combo.setCurrentText("English (US)") # Default language
        settings_layout.addWidget(self.language_combo, 2, 1, 1, 2)

        self.style_combo_label = QLabel("Style (preset):")
        settings_layout.addWidget(self.style_combo_label, 3, 0)
        self.style_prompt_combo = QComboBox()
        self.style_prompt_combo.addItems(STYLE_PROMPT_OPTIONS.keys())
        self.style_prompt_combo.currentIndexChanged.connect(self.update_style_prompt_text)
        settings_layout.addWidget(self.style_prompt_combo, 3, 1, 1, 2)

        self.prompt_label = QLabel("Prompt (EN):")
        settings_layout.addWidget(self.prompt_label, 4, 0, Qt.AlignmentFlag.AlignTop)
        self.style_prompt_input = QTextEdit()
        self.style_prompt_input.setPlaceholderText("Custom 'Style Prompt' in English...")
        self.style_prompt_input.setMaximumHeight(60)
        settings_layout.addWidget(self.style_prompt_input, 4, 1, 1, 2)
        
        # NEW: Slider for speech rate
        self.speed_label = QLabel("Speech Rate: 1.00x")
        settings_layout.addWidget(self.speed_label, 5, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400) # Range 0.25x to 4.00x
        self.speed_slider.setValue(100) # Default speed 1.00x
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText("Speech Rate:" + f" {v/100:.2f}x"))
        settings_layout.addWidget(self.speed_slider, 5, 1, 1, 2)

        self.temp_label = QLabel(f"Temperature: 1.0")
        settings_layout.addWidget(self.temp_label, 6, 0)
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 20)
        self.temp_slider.setValue(10)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_label.setText("Temperature:" + f" {v/10:.1f}"))
        settings_layout.addWidget(self.temp_slider, 6, 1, 1, 2)
        
        right_layout_tab1.addWidget(self.settings_group)

        self.control_group = QGroupBox("Segmentation and Generation Control")
        control_layout = QVBoxLayout(self.control_group)
        
        self.use_full_text_checkbox = QCheckBox("Use full text as one segment")
        self.use_full_text_checkbox.stateChanged.connect(self.toggle_segmentation_controls)
        control_layout.addWidget(self.use_full_text_checkbox)

        segment_count_layout = QHBoxLayout()
        self.segment_count_slider = QSlider(Qt.Orientation.Horizontal)
        self.segment_count_slider.setRange(1, 10)
        self.segment_count_slider.setValue(3)
        self.segment_count_label = QLabel(f"Sentences/Seg.: {self.segment_count_slider.value()}")
        segment_count_layout.addWidget(self.segment_count_label)
        segment_count_layout.addWidget(self.segment_count_slider)
        control_layout.addLayout(segment_count_layout)

        self.split_button = QPushButton("Split text into segments")
        self.split_button.clicked.connect(self.split_text_and_display)
        control_layout.addWidget(self.split_button)

        self.segment_count_slider.valueChanged.connect(self.update_split_button_on_slider_change)
        self.update_split_button_on_slider_change(self.segment_count_slider.value())

        self.generate_all_button = QPushButton("Generate ALL Segments")
        self.generate_all_button.clicked.connect(self.start_batch_generation)
        self.generate_all_button.setEnabled(False)
        control_layout.addWidget(self.generate_all_button)

        right_layout_tab1.addWidget(self.control_group)
        right_layout_tab1.addStretch()
        tab1_layout.addWidget(right_panel_tab1, 1)

        # --- TAB 2: Segments ---
        self.tab2 = QWidget()
        self.tabs.addTab(self.tab2, "2. Segments Editor")
        tab2_layout = QVBoxLayout(self.tab2)
        self.segments_group = QGroupBox("Segments")
        segments_main_layout = QVBoxLayout(self.segments_group)

        self.add_segment_button = QPushButton("➕ Add Empty Segment")
        self.add_segment_button.clicked.connect(self.add_new_segment)
        segments_main_layout.addWidget(self.add_segment_button)

        self.segments_scroll = QScrollArea()
        self.segments_scroll.setWidgetResizable(True)
        self.segments_container = QWidget()
        self.segments_layout = QVBoxLayout(self.segments_container)
        self.segments_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.segments_scroll.setWidget(self.segments_container)
        segments_main_layout.addWidget(self.segments_scroll)
        tab2_layout.addWidget(self.segments_group)

        # --- TAB 3: Final Output ---
        self.tab3 = QWidget()
        self.tabs.addTab(self.tab3, "3. Final Output")
        tab3_layout = QVBoxLayout(self.tab3)
        tab3_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.full_gen_group = QGroupBox("Final Output")
        self.full_gen_group.setMaximumWidth(1000)
        self.full_gen_layout = QHBoxLayout(self.full_gen_group)

        self.full_waveform_label = QLabel()
        self.full_waveform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.full_waveform_label.setMinimumHeight(80)
        self.full_waveform_label.setMinimumWidth(300)
        self.full_gen_layout.addWidget(self.full_waveform_label, 2)

        full_button_layout = QVBoxLayout()
        self.merge_segments_button = QPushButton("➕ Merge Segments")
        self.merge_segments_button.clicked.connect(self.merge_segments_audio)
        self.merge_segments_button.setEnabled(False)
        full_button_layout.addWidget(self.merge_segments_button)

        play_save_layout = QHBoxLayout()
        self.play_full_button = QPushButton("▶ Play Full")
        self.play_full_button.setEnabled(False)
        self.play_full_button.clicked.connect(self.play_full_audio)
        play_save_layout.addWidget(self.play_full_button)

        self.save_full_button = QPushButton("Save")
        self.save_full_button.setEnabled(False)
        self.save_full_button.clicked.connect(self.save_audio)
        play_save_layout.addWidget(self.save_full_button)
        full_button_layout.addLayout(play_save_layout)

        self.stop_all_button = QPushButton("◼ STOP")
        self.stop_all_button.setEnabled(False)
        self.stop_all_button.clicked.connect(self.stop_all_audio)
        full_button_layout.addWidget(self.stop_all_button)

        self.full_gen_layout.addLayout(full_button_layout, 1)
        tab3_layout.addWidget(self.full_gen_group)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.pro_char_label = QLabel("Pro Chars: 0")
        self.flash_char_label = QLabel("Flash Chars: 0")
        self.tokens_label = QLabel("In/Out Tokens: 0/0")
        self.cost_label = QLabel("Cost: $0.000000")
        self.status_bar.addPermanentWidget(self.pro_char_label)
        self.status_bar.addPermanentWidget(self.flash_char_label)
        self.status_bar.addPermanentWidget(self.tokens_label)
        self.status_bar.addPermanentWidget(self.cost_label)
        
        self.status_bar.showMessage("Application ready.")

    def update_full_waveform(self, png_path: str):
        pixmap = QPixmap(png_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.full_waveform_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.full_waveform_label.setPixmap(scaled_pixmap)
            self.full_waveform_label.setText("")

    def update_segment_waveform(self, index: int, png_path: str):
        waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{index}")
        if waveform_label and png_path:
            pixmap = QPixmap(png_path)
            if not pixmap.isNull():
                 scaled_pixmap = pixmap.scaled(waveform_label.width(), 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                 waveform_label.setPixmap(scaled_pixmap)
                 waveform_label.setText("")

    def update_style_prompt_text(self, index):
        selected_style_name = self.style_prompt_combo.currentText()
        selected_en_prompt = STYLE_PROMPT_OPTIONS.get(selected_style_name, "")
        self.style_prompt_input.setText(selected_en_prompt)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("File")
        
        self.new_action = QAction("New Project", self); self.new_action.setShortcut(QKeySequence.StandardKey.New); self.new_action.triggered.connect(self.new_project); self.file_menu.addAction(self.new_action)
        self.open_action = QAction("Load Project...", self); self.open_action.setShortcut(QKeySequence.StandardKey.Open); self.open_action.triggered.connect(self.load_project); self.file_menu.addAction(self.open_action)
        self.save_action = QAction("Save Project...", self); self.save_action.setShortcut(QKeySequence.StandardKey.Save); self.save_action.triggered.connect(self.save_project); self.file_menu.addAction(self.save_action)
        
        self.file_menu.addSeparator()
        self.save_audio_action = QAction("Save Full WAV...", self); self.save_audio_action.triggered.connect(self.save_audio); self.file_menu.addAction(self.save_audio_action)
        self.file_menu.addSeparator()
        
        self.exit_action = QAction("Exit", self); self.exit_action.setShortcut(QKeySequence.StandardKey.Quit); self.exit_action.triggered.connect(self.close); self.file_menu.addAction(self.exit_action)
        
        self.tools_menu = menu_bar.addMenu("Tools")
        self.clean_temp_action = QAction("Clear temporary files", self); self.clean_temp_action.triggered.connect(self.temp_file_manager.cleanup); self.tools_menu.addAction(self.clean_temp_action)
        self.set_api_key_action = QAction("Set API Key...", self); self.set_api_key_action.triggered.connect(self.set_api_key_dialog); self.tools_menu.addAction(self.set_api_key_action)
        self.set_pricing_action = QAction("Set Rates (Pricing)...", self); self.set_pricing_action.triggered.connect(self.set_pricing_dialog); self.tools_menu.addAction(self.set_pricing_action)
        
        self.show_logs_action = QAction("Show Logs...", self)
        self.show_logs_action.triggered.connect(self.show_log_viewer)
        self.tools_menu.addAction(self.show_logs_action)
        
        # Language menu was removed
        
        self.help_menu = menu_bar.addMenu("Help")
        self.about_action = QAction("About", self); self.about_action.triggered.connect(lambda: QMessageBox.information(self, "About", "Gemini TTS Generator: A demonstration of segmented text-to-speech conversion using the Google Gemini API")); self.help_menu.addAction(self.about_action)

    def show_log_viewer(self):
        if not self.log_viewer:
            self.log_viewer = LogViewerDialog(self)
        self.log_viewer.show()
        self.log_viewer.raise_()
        self.log_viewer.activateWindow()

    def set_api_key_dialog(self):
        global GEMINI_API_KEY
        key, ok = QInputDialog.getText(self, "API Key Settings", "Enter your Gemini API key:", QLineEdit.EchoMode.Password)
        if ok and key:
            GEMINI_API_KEY = key.strip()
            self.save_settings()
            self.status_bar.showMessage("API key was successfully saved.")
            self.fetch_dynamic_models() # Try loading models with the new key
            
    def set_pricing_dialog(self):
        pro_price, ok1 = QInputDialog.getDouble(self, "Pricing (Pro)", "Rate per 1 million tokens/chars for PRO model (in $):", self.pro_rate, 0, 1000, 6)
        if ok1:
            self.pro_rate = pro_price
            flash_price, ok2 = QInputDialog.getDouble(self, "Pricing (Flash)", "Rate per 1 million tokens/chars for FLASH model (in $):", self.flash_rate, 0, 1000, 6)
            if ok2:
                self.flash_rate = flash_price
                self.save_settings()
                self.update_char_count_labels()
                self.status_bar.showMessage("Rates successfully saved.")
            
    def insert_markup_tag_into_segment(self, tag: str, text_widget: QTextEdit):
        if text_widget:
            text_widget.setFocus()
            text_widget.textCursor().insertText(tag + " ")
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            text_widget.setTextCursor(cursor)
        else:
             self.show_error_message("An error occurred: segment text field not found.")

    # --- ENHANCED: MULTITASKING ---
    def start_generation(self, segment_index: int):
        # --- NEW: Check if API key exists ---
        if not GEMINI_API_KEY:
            self.show_error_message("Gemini API key not found.\n\nSet it in menu 'Tools' -> 'Set API Key...'.")
            return

        # If batch generation is running, do nothing
        if self.batch_thread and self.batch_thread.isRunning():
            self.show_error_message("Batch generation in progress. Cancel it to generate a single segment.")
            return

        # If generation is already running for this segment, do nothing
        # CHANGE: Check for standard Python thread
        if segment_index in self.active_single_gen_threads and self.active_single_gen_threads[segment_index].is_alive():
            self.status_bar.showMessage("Generating...")
            return

        text_widget = self.segment_data[segment_index].get("text_widget")
        if not text_widget:
            self.show_error_message("Segment does not contain text UI element.")
            return

        text_to_generate = text_widget.toPlainText().strip()
        if not text_to_generate:
            self.show_error_message("Segment contains no text to generate.")
            return

        self.set_segment_ui_enabled(segment_index, False)
        self.segment_data[segment_index]["text"] = text_to_generate

        selected_model_display_name = self.gemini_model_combo.currentText()
        selected_model = GEMINI_TTS_MODELS.get(selected_model_display_name, list(GEMINI_TTS_MODELS.values())[0])
        style_prompt = self.style_prompt_input.toPlainText().strip()
        
        language_display_name = self.language_combo.currentText()
        language_code = SUPPORTED_LANGUAGES.get(language_display_name, "en-US")
        speaking_rate = self.speed_slider.value() / 100.0

        # --- ENHANCED: Load voice for specific segment ---
        segment_voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{segment_index}")
        selected_voice = segment_voice_combo.currentData() if segment_voice_combo else self.gemini_voice_combo.currentData()

        waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{segment_index}")
        if waveform_label:
            waveform_label.setText(f"Generating...")
            waveform_label.setPixmap(QPixmap())

        params = {
            "text": text_to_generate,
            "prompt": style_prompt,
            "voice_name": selected_voice,
            "temperature": self.temp_slider.value() / 10.0,
            "model": selected_model,
            "language_code": language_code,
            "speaking_rate": speaking_rate,
        }

        # --- NEW LOGIC USING threading.Thread ---
        
        # 1. Create signals object
        signals = WorkerSignals()
        
        # 2. Connect signals to methods in the main window
        signals.finished.connect(lambda result, idx=segment_index: self.on_generation_finished(result, idx))
        signals.error.connect(lambda error_msg, idx=segment_index: self.on_generation_error(error_msg, idx))
        
        # 3. Create worker instance (no longer a QObject)
        worker = GeminiWorker(params, signals)
        
        # 4. Create and start standard Python thread
        thread = Thread(target=worker.run, daemon=True)
        # Store thread reference to check status (is_alive)
        self.active_single_gen_threads[segment_index] = thread

        self.status_bar.showMessage("Generating speech (Segment {0})...".format(segment_index + 1))
        thread.start()

    def on_generation_finished(self, result, segment_index):
        audio_content = result["audio_content"]
        char_count = result["char_count"]
        model_used = result["model_used"]
        in_tok = result.get("in_tokens", 0)
        out_tok = result.get("out_tokens", 0)

        # CHANGE: Remove thread reference after completion
        self.active_single_gen_threads.pop(segment_index, None)

        self.in_tokens_count += in_tok
        self.out_tokens_count += out_tok

        units = in_tok + out_tok if (in_tok + out_tok) > 0 else char_count

        # Update character counter and cost
        if "pro" in model_used:
            self.pro_char_count += char_count
            self.total_cost += (units * self.pro_rate / 1000000.0)
        elif "flash" in model_used:
            self.flash_char_count += char_count
            self.total_cost += (units * self.flash_rate / 1000000.0)
        self.update_char_count_labels()

        self.segment_data[segment_index]["audio"] = audio_content
        audio_path = self.temp_file_manager.create_temp_file(".wav", audio_content)
        self.segment_data[segment_index]["audio_temp_path"] = audio_path

        png_data = create_waveform_png_data(audio_content, width=800, height=70)
        png_path = self.temp_file_manager.create_temp_file(".png", png_data)
        self.segment_data[segment_index]["png_temp_path"] = png_path

        self.update_segment_waveform(segment_index, png_path)

        self.set_segment_ui_enabled(segment_index, True)
        play_button = self.get_segment_play_button(segment_index)
        play_button.setEnabled(True)
        self.update_segment_play_button_ui(segment_index, QMediaPlayer.PlaybackState.StoppedState)

        self.audio_content = None
        self.full_audio_temp_path = None
        self.play_full_button.setEnabled(False)
        self.save_full_button.setEnabled(False)
        self.full_waveform_label.setText("Waveform: Merge segments...")
        self.full_waveform_label.setPixmap(QPixmap())

        can_merge = all(s.get("audio") is not None for s in self.segment_data)
        self.merge_segments_button.setEnabled(can_merge)

        self.status_bar.showMessage("Segment {0} generated.".format(segment_index + 1))

    def on_generation_error(self, error_message, segment_index):
        self.active_single_gen_threads.pop(segment_index, None)

        waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{segment_index}")
        if waveform_label:
            waveform_label.setText("Generation FAILED.")
            waveform_label.setPixmap(QPixmap())

        self.set_segment_ui_enabled(segment_index, True)
        self.show_error_message("Error generating segment {0}:\n{1}".format(segment_index + 1, error_message))
        self.status_bar.showMessage("Error occurred during generation of segment {0}.".format(segment_index + 1))

    def cleanup_worker_and_thread(self):
         pass

    def start_batch_generation(self):
        if not GEMINI_API_KEY:
            self.show_error_message("Gemini API key not found.\n\nSet it in menu 'Tools' -> 'Set API Key...'.")
            return

        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()
            return

        active_single_threads = {k: v for k, v in self.active_single_gen_threads.items() if v.is_alive()}
        if active_single_threads:
             self.show_error_message("Individual segments are generating. Batch generation cannot be started.")
             return

        # If use full text checkbox is checked, automatically update segment before generating
        if self.use_full_text_checkbox.isChecked():
            main_text = self.text_input.toPlainText().strip()
            if not main_text:
                self.show_error_message("Please enter text to process.")
                return
            
            needs_split = True
            if len(self.segment_data) == 1:
                # Check text_widget and plain text
                current_segment_text = self.segment_data[0].get("text_widget").toPlainText().strip() if self.segment_data[0].get("text_widget") else self.segment_data[0].get("text", "")
                if current_segment_text == main_text:
                    needs_split = False
            
            if needs_split:
                self.split_text_and_display()
                if not self.segment_data:
                    return

        segments_to_process = []
        for i, s in enumerate(self.segment_data):
             if s.get("audio") is None:
                 text = s["text_widget"].toPlainText().strip() if s.get("text_widget") else s.get("text", "")
                 if text:
                     s["text"] = text
                     voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{i}")
                     voice = voice_combo.currentData() if voice_combo else self.gemini_voice_combo.currentData()
                     segments_to_process.append({
                         "text": text,
                         "voice": voice,
                         "original_index": i
                     })
        
        if not segments_to_process:
            self.show_error_message("All segments already have audio generated or are empty.")
            return

        self.stop_all_audio()

        prompt = self.style_prompt_input.toPlainText().strip()
        temperature = self.temp_slider.value() / 10.0
        model = GEMINI_TTS_MODELS.get(self.gemini_model_combo.currentText())
        
        language_display_name = self.language_combo.currentText()
        language_code = SUPPORTED_LANGUAGES.get(language_display_name, "en-US")
        speaking_rate = self.speed_slider.value() / 100.0

        self.batch_thread = QThread()
        self.batch_worker = SegmentBatchWorker(
            segments_to_process=segments_to_process,
            prompt=prompt,
            temperature=temperature,
            model=model,
            temp_file_manager=self.temp_file_manager,
            language_code=language_code,
            speaking_rate=speaking_rate
        )
        self.batch_worker.moveToThread(self.batch_thread)

        self.batch_thread.started.connect(self.batch_worker.run)
        self.batch_worker.segment_generated.connect(self.handle_segment_generated)
        self.batch_worker.finished.connect(self.handle_batch_finished)
        self.batch_worker.error.connect(self.handle_batch_error)
        self.batch_worker.status_update.connect(self.status_bar.showMessage)

        self.set_ui_enabled(False, batch_in_progress=True)
        self.generate_all_button.setText("◼ Cancel Generation")
        try: self.generate_all_button.clicked.disconnect()
        except TypeError: pass
        self.generate_all_button.clicked.connect(self.cancel_batch_generation)

        for s_info in segments_to_process:
            idx = s_info["original_index"]
            waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{idx}")
            if waveform_label:
                waveform_label.setText("Waiting...")
                waveform_label.setPixmap(QPixmap())

        self.status_bar.showMessage("Starting batch generation of {0} segments...".format(len(segments_to_process)))
        self.tabs.setCurrentIndex(1)
        self.batch_thread.start()

    def cancel_batch_generation(self):
        if self.batch_thread and self.batch_thread.isRunning() and self.batch_worker:
            self.batch_worker.cancel()
            self.status_bar.showMessage("Canceling generation...")
        else:
             self.set_ui_enabled(True)

    def handle_segment_generated(self, index: int, result: dict):
        char_count = result["char_count"]
        model_used = result["model_used"]
        in_tok = result.get("in_tokens", 0)
        out_tok = result.get("out_tokens", 0)

        self.in_tokens_count += in_tok
        self.out_tokens_count += out_tok

        units = in_tok + out_tok if (in_tok + out_tok) > 0 else char_count

        if "pro" in model_used:
            self.pro_char_count += char_count
            self.total_cost += (units * self.pro_rate / 1000000.0)
        elif "flash" in model_used:
            self.flash_char_count += char_count
            self.total_cost += (units * self.flash_rate / 1000000.0)
        self.update_char_count_labels()
        
        self.segment_data[index]["audio"] = result["audio_content"]
        self.segment_data[index]["audio_temp_path"] = result["audio_temp_path"]
        self.segment_data[index]["png_temp_path"] = result["png_temp_path"]

        play_button = self.get_segment_play_button(index)
        if play_button:
            play_button.setEnabled(True)
            self.update_segment_play_button_ui(index, QMediaPlayer.PlaybackState.StoppedState)

        self.update_segment_waveform(index, result["png_temp_path"])

        self.segments_container.findChild(QPushButton, f"gen_button_{index}").setEnabled(True)
        self.segments_container.findChild(QPushButton, f"delete_button_{index}").setEnabled(True)

        if all(s.get("audio") is not None for s in self.segment_data) and not self.batch_worker._is_cancelled:
            self.merge_segments_audio()

        can_merge = all(s.get("audio") is not None for s in self.segment_data)
        self.merge_segments_button.setEnabled(can_merge)

    def handle_batch_finished(self):
        was_cancelled = self.batch_worker and self.batch_worker._is_cancelled

        if self.batch_thread:
            self.batch_thread.quit()
            self.batch_thread.wait()
            self.batch_thread.deleteLater()
            self.batch_thread = None
        self.batch_worker = None

        self.set_ui_enabled(True)

        if not was_cancelled:
            self.status_bar.showMessage("Batch generation complete! Audio merged automatically.")
            self.tabs.setCurrentIndex(2) # Switch to final output
        else:
            self.status_bar.showMessage("Batch generation canceled.")
            can_merge = all(s.get("audio") is not None for s in self.segment_data)
            self.merge_segments_button.setEnabled(can_merge and len(self.segment_data) > 0)

    def handle_batch_error(self, message: str):
        if self.batch_thread:
            self.batch_thread.quit()
            self.batch_thread.wait()
            self.batch_thread.deleteLater()
            self.batch_thread = None
        self.batch_worker = None

        self.set_ui_enabled(True)
        self.show_error_message("Batch generation error: {0}".format(message))
        self.status_bar.showMessage("Error: Batch generation failed.")

    def new_project(self):
        print("[INFO] Creating a new project (cleared text inputs and active segments).")
        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()
        
        # Terminate all running single-threads
        for index, thread in list(self.active_single_gen_threads.items()):
            if thread.is_alive():
                 print(f"INFO: Terminating running single-thread for segment {index+1} (daemon thread should exit upon completion).")
            # Remove reference, even though thread might still run briefly
            del self.active_single_gen_threads[index]

        self.audio_content = None
        self.full_audio_temp_path = None
        self.segment_data = []
        self.active_text_widget = None
        self.text_input.clear()
        self.style_prompt_input.clear()
        self.style_prompt_combo.setCurrentIndex(0)
        
        # --- ENHANCED: Reset counters ---
        self.pro_char_count = 0
        self.flash_char_count = 0
        self.in_tokens_count = 0
        self.out_tokens_count = 0
        self.total_cost = 0.0
        self.update_char_count_labels()

        self.temp_file_manager.cleanup()
        self.display_segments()

        self.merge_segments_button.setEnabled(False)
        self.play_full_button.setEnabled(False)
        self.save_full_button.setEnabled(False)
        self.generate_all_button.setEnabled(False)
        self.stop_all_button.setEnabled(False)

        self.full_waveform_label.setText("Waveform: Merge segments...")
        self.full_waveform_label.setPixmap(QPixmap())
        self.status_bar.showMessage("New project created.")
        self.tabs.setCurrentIndex(0)

    def save_project(self):
        # --- CHANGE: Dialog opens in the /project directory ---
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Project...", PROJECTS_DIR, "Gemini TTS Project (*.gtts)")

        if file_path:
            try:
                print(f"[INFO] Saving project to: {file_path}...")
                settings = {
                    "model_display_name": self.gemini_model_combo.currentText(),
                    "voice": self.gemini_voice_combo.currentData(),
                    "prompt": self.style_prompt_input.toPlainText().strip(),
                    "temperature": self.temp_slider.value(),
                    "segment_count": self.segment_count_slider.value(),
                    "full_text": self.text_input.toPlainText().strip(),
                    "language": self.language_combo.currentText(),
                    "speed": self.speed_slider.value(),
                    # --- ENHANCED: Save counters ---
                    "pro_chars": self.pro_char_count,
                    "flash_chars": self.flash_char_count,
                }

                segments = []
                base_dir = os.path.dirname(file_path)
                project_name = os.path.splitext(os.path.basename(file_path))[0]
                assets_dir = os.path.join(base_dir, f"{project_name}_assets")
                os.makedirs(assets_dir, exist_ok=True)

                for i, data in enumerate(self.segment_data):
                    text = data.get("text_widget").toPlainText().strip() if data.get("text_widget") else data["text"]
                    
                    # --- ENHANCED: Get voice from segment ---
                    voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{i}")
                    voice = voice_combo.currentData() if voice_combo else data["voice"]
                    
                    segment_info = {"text": text, "voice": voice}
                    if data.get("audio_temp_path") and os.path.exists(data["audio_temp_path"]):
                        wav_filename = f"segment_{i+1}.wav"
                        shutil.copy(data["audio_temp_path"], os.path.join(assets_dir, wav_filename))
                        segment_info["wav_file"] = wav_filename
                    if data.get("png_temp_path") and os.path.exists(data["png_temp_path"]):
                        png_filename = f"segment_{i+1}.png"
                        shutil.copy(data["png_temp_path"], os.path.join(assets_dir, png_filename))
                        segment_info["png_file"] = png_filename
                    segments.append(segment_info)

                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump({"settings": settings, "segments": segments, "assets_dir_name": os.path.basename(assets_dir)}, f, indent=4)
                print(f"[SUCCESS] Project successfully saved to: {file_path}.")
                self.status_bar.showMessage("Project saved successfully to: {0}".format(file_path))
            except Exception as e:
                print(f"[ERROR] Failed to save project to {file_path}: {e}")
                self.show_error_message("Error saving project: {0}".format(e))

    def load_project(self):
        # --- CHANGE: Dialog opens in the /project directory ---
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Project", PROJECTS_DIR, "Gemini TTS Project (*.gtts)")

        if file_path:
            try:
                print(f"[INFO] Loading project from: {file_path}...")
                with open(file_path, "r", encoding="utf-8") as f:
                    project_data = json.load(f)

                self.new_project()

                settings = project_data.get("settings", {})
                segments_info = project_data.get("segments", [])
                assets_dir_name = project_data.get("assets_dir_name")

                project_base_dir = os.path.dirname(file_path)
                assets_dir_path = os.path.join(project_base_dir, assets_dir_name)

                if settings.get("model_display_name"): self.gemini_model_combo.setCurrentText(settings["model_display_name"])
                
                voice_to_set = settings.get("voice")
                if voice_to_set:
                    idx = self.gemini_voice_combo.findData(voice_to_set)
                    if idx != -1: self.gemini_voice_combo.setCurrentIndex(idx)
                    
                self.style_prompt_input.setText(settings.get("prompt", ""))
                current_prompt = settings.get("prompt", "")
                if current_prompt in STYLE_PROMPT_OPTIONS.values():
                    style_key = [k for k, v in STYLE_PROMPT_OPTIONS.items() if v == current_prompt]
                    if style_key: self.style_prompt_combo.setCurrentText(style_key[0])

                self.temp_slider.setValue(settings.get("temperature", 10))
                self.segment_count_slider.setValue(settings.get("segment_count", 3))
                self.text_input.setText(settings.get("full_text", ""))

                if settings.get("language") in SUPPORTED_LANGUAGES:
                    self.language_combo.setCurrentText(settings["language"])
                self.speed_slider.setValue(settings.get("speed", 100))
                
                # --- ENHANCED: Load counters ---
                self.pro_char_count = settings.get("pro_chars", 0)
                self.flash_char_count = settings.get("flash_chars", 0)
                self.update_char_count_labels()

                if segments_info:
                    new_segment_data = []
                    for s_info in segments_info:
                        text, temp_wav_path, temp_png_path, audio_content = s_info["text"], None, None, None
                        if s_info.get("wav_file"):
                            source_wav = os.path.join(assets_dir_path, s_info["wav_file"])
                            if os.path.exists(source_wav):
                                with open(source_wav, "rb") as f: audio_content = f.read()
                                temp_wav_path = self.temp_file_manager.create_temp_file(".wav", audio_content)
                        if s_info.get("png_file"):
                            source_png = os.path.join(assets_dir_path, s_info["png_file"])
                            if os.path.exists(source_png):
                                with open(source_png, "rb") as f: png_data = f.read()
                                temp_png_path = self.temp_file_manager.create_temp_file(".png", png_data)
                        
                        # --- ENHANCED: Load voice for segment ---
                        segment_voice = s_info.get("voice", self.gemini_voice_combo.currentData())
                        new_segment_data.append({"text": text, "audio": audio_content, "audio_temp_path": temp_wav_path, "png_temp_path": temp_png_path, "text_widget": None, "voice": segment_voice})
                    
                    self.segment_data = new_segment_data
                    self.display_segments()
                    self.tabs.setCurrentIndex(1)

                    if all(s.get("audio") for s in self.segment_data):
                         self.merge_segments_button.setEnabled(True)
                         self.generate_all_button.setEnabled(True)
                         self.merge_segments_audio()
                         self.tabs.setCurrentIndex(2)
                    else:
                         self.generate_all_button.setEnabled(True)
                    print(f"[SUCCESS] Project loaded successfully with {len(self.segment_data)} segments.")
                    self.status_bar.showMessage("Project loaded with {0} segments.".format(len(self.segment_data)))
                else:
                    print("[SUCCESS] Project loaded successfully (empty segments list).")
                    self.status_bar.showMessage("Project loaded. Split text into segments.")
            except Exception as e:
                print(f"[ERROR] Failed to load project from {file_path}: {e}")
                self.show_error_message("Error loading project: {0}".format(e))
                self.new_project()

    def import_txt_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import TXT File", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                print(f"[INFO] Importing text file: {file_path}...")
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.text_input.setText(content)
                print(f"[SUCCESS] Text successfully imported from file: {file_path}.")
                self.status_bar.showMessage("Text imported successfully from: {0}".format(os.path.basename(file_path)))
            except UnicodeDecodeError:
                try:
                    with open(file_path, "r", encoding="cp1250") as f:
                        content = f.read()
                    self.text_input.setText(content)
                    print(f"[SUCCESS] Text successfully imported from file (CP1250 encoding): {file_path}.")
                    self.status_bar.showMessage("Text imported successfully from: {0}".format(os.path.basename(file_path)))
                except Exception as e:
                    print(f"[ERROR] Failed to import text file {file_path}: {e}")
                    self.show_error_message("Error reading text file: {0}".format(e))
            except Exception as e:
                print(f"[ERROR] Failed to import text file {file_path}: {e}")
                self.show_error_message("Error reading text file: {0}".format(e))
    
    # --- MODIFIED FUNCTION ---
    def split_text_and_display(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            self.show_error_message("Please enter text to process.")
            return

        print(f"[INFO] Splitting text. Mode: {'Single segment' if self.use_full_text_checkbox.isChecked() else 'Sentence count split'}...")
        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()

        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()

        sentences = []
        # --- CHANGE: Deciding based on checkbox ---
        if self.use_full_text_checkbox.isChecked():
            sentences.append(text)
        else:
            sentences_per_segment = self.segment_count_slider.value()
            sentences = _split_text_into_segments(text, sentences_per_segment)

        if not sentences:
            print("[ERROR] Could not process text into segments.")
            self.show_error_message("Could not process text into segments.")
            return

        self.audio_content = None
        self.full_audio_temp_path = None
        
        default_voice = self.gemini_voice_combo.currentData()
        self.segment_data = [{"text": s, "audio": None, "audio_temp_path": None, "png_temp_path": None, "text_widget": None, "voice": default_voice} for s in sentences]

        self.display_segments()

        self.merge_segments_button.setEnabled(False)
        self.play_full_button.setEnabled(False)
        self.save_full_button.setEnabled(False)
        self.generate_all_button.setEnabled(True)

        self.full_waveform_label.setText("Waveform: Merge segments...")
        self.full_waveform_label.setPixmap(QPixmap())
        
        if self.use_full_text_checkbox.isChecked():
            print("[SUCCESS] Split completed. Created 1 segment from the full text.")
            self.status_bar.showMessage("Created 1 segment from the full text.")
        else:
            print(f"[SUCCESS] Split completed. Text split into {len(self.segment_data)} segments.")
            self.status_bar.showMessage("Text split into {0} segments.".format(len(self.segment_data)))
        
        self.tabs.setCurrentIndex(1) # Automatically switch to segments tab


    def delete_segment(self, index: int):
        if 0 <= index < len(self.segment_data):
            print(f"[INFO] Deleting segment {index + 1}...")
            if self.player.source().isLocalFile() and self.player.source().toLocalFile() == self.segment_data[index].get("audio_temp_path"):
                self.player.stop()
            
            # CHANGE: Stop single-thread
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                # Daemon thread will exit itself, just remove reference so UI doesn't wait
                 del self.active_single_gen_threads[index] 
                 
            del self.segment_data[index]
            if not self.segment_data:
                self.generate_all_button.setEnabled(False)
                self.merge_segments_button.setEnabled(False)
            self.audio_content = None
            self.full_audio_temp_path = None
            self.play_full_button.setEnabled(False)
            self.save_full_button.setEnabled(False)
            self.full_waveform_label.setText("Waveform: Merge segments...")
            self.full_waveform_label.setPixmap(QPixmap())
            self.display_segments()
            can_merge = all(s.get("audio") for s in self.segment_data)
            self.merge_segments_button.setEnabled(can_merge and len(self.segment_data) > 0)
            print(f"[SUCCESS] Segment deleted. {len(self.segment_data)} segments remaining.")
            self.status_bar.showMessage("Segment deleted. {0} segments remaining.".format(len(self.segment_data)))

    def display_segments(self):
        while self.segments_layout.count():
            child = self.segments_layout.takeAt(0)
            if child.widget():
                if isinstance(child.widget().findChild(QTextEdit), CustomTextEdit):
                    try: child.widget().findChild(QTextEdit).focus_in_signal.disconnect(self.set_active_text_widget)
                    except TypeError: pass
                child.widget().deleteLater()

        for i, data in enumerate(self.segment_data):
            segment_widget = QWidget()
            segment_widget.setObjectName("SegmentRow")
            segment_grid = QGridLayout(segment_widget)

            # --- ENHANCED: Vertical move buttons ---
            move_buttons_layout = QVBoxLayout()
            up_button = QPushButton("▲")
            up_button.setObjectName(f"up_button_{i}")
            up_button.setFixedSize(25, 25)
            up_button.setEnabled(i > 0)
            up_button.clicked.connect(lambda checked, idx=i: self.move_segment_up(idx))
            down_button = QPushButton("▼")
            down_button.setObjectName(f"down_button_{i}")
            down_button.setFixedSize(25, 25)
            down_button.setEnabled(i < len(self.segment_data) - 1)
            down_button.clicked.connect(lambda checked, idx=i: self.move_segment_down(idx))
            move_buttons_layout.addWidget(up_button)
            move_buttons_layout.addWidget(down_button)
            segment_grid.addLayout(move_buttons_layout, 0, 0, 2, 1, Qt.AlignmentFlag.AlignVCenter)


            index_label = QLabel(f"<b style='font-size: 14pt; color: #0095ff;'>{i + 1}.</b>")
            segment_grid.addWidget(index_label, 0, 1, 2, 1, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)

            text_input = CustomTextEdit()
            text_input.focus_in_signal.connect(self.set_active_text_widget)
            text_input.setText(data["text"])
            text_input.setFixedHeight(110) # Fixed height for approx 5 lines
            text_input.setObjectName(f"text_input_segment_{i}")
            self.segment_data[i]["text_widget"] = text_input
            segment_grid.addWidget(text_input, 0, 2, 1, 2)

            waveform_label = QLabel("Waveform not generated")
            waveform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            waveform_label.setObjectName(f"waveform_label_{i}")
            waveform_label.setMinimumHeight(60)
            if data.get("png_temp_path"):
                 pixmap = QPixmap(data["png_temp_path"])
                 if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(400, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    waveform_label.setPixmap(scaled_pixmap)
                    waveform_label.setText("")
            segment_grid.addWidget(waveform_label, 1, 2)

            control_layout = QHBoxLayout()
            tag_button = QPushButton("Insert Tag");
            tag_menu = QMenu(self)
            for group_name, tags in MARKUP_TAGS.items():
                group_menu = tag_menu.addMenu(group_name)
                for tag, tooltip in tags.items():
                    action = QAction(tag, self)
                    action.setToolTip(tooltip)
                    action.triggered.connect(lambda checked, t=tag, w=text_input: self.insert_markup_tag_into_segment(t, w))
                    group_menu.addAction(action)
            tag_button.setMenu(tag_menu)
            control_layout.addWidget(tag_button)

            # --- ENHANCED: Voice selection for segment ---
            voice_combo = QComboBox()
            voice_combo.setObjectName(f"voice_combo_{i}")
            for voice, gender in GEMINI_VOICE_INFO.items():
                gender_char = "M" if gender == "Male" else "F"
                voice_combo.addItem(f"{voice} ({gender_char})", voice)
            current_voice = data.get("voice", self.gemini_voice_combo.currentData())
            voice_idx = voice_combo.findData(current_voice)
            if voice_idx != -1:
                voice_combo.setCurrentIndex(voice_idx)
            voice_combo.currentIndexChanged.connect(lambda _, idx=i: self.on_segment_voice_changed(idx))
            segment_grid.addWidget(voice_combo, 2, 2)


            gen_button = QPushButton("🔊 Generate"); gen_button.clicked.connect(lambda checked, idx=i: self.start_generation(segment_index=idx)); gen_button.setObjectName(f"gen_button_{i}"); control_layout.addWidget(gen_button)
            play_button = QPushButton("▶ Play"); play_button.setEnabled(data.get("audio") is not None); play_button.setObjectName(f"play_button_{i}"); play_button.clicked.connect(lambda checked, idx=i: self.play_segment_audio(idx)); control_layout.addWidget(play_button)
            
            # --- ENHANCED: Added silence button ---
            silence_button = QPushButton("🔇 Silence"); silence_button.setObjectName(f"silence_button_{i}"); silence_button.clicked.connect(lambda checked, idx=i: self.add_silence_to_segment(idx)); control_layout.addWidget(silence_button)
            
            delete_button = QPushButton("🗑 Delete"); delete_button.setObjectName(f"delete_button_{i}"); delete_button.clicked.connect(lambda checked, idx=i: self.delete_segment(idx)); control_layout.addWidget(delete_button)

            segment_grid.addLayout(control_layout, 1, 3, Qt.AlignmentFlag.AlignVCenter)
            segment_grid.setColumnStretch(2, 3)
            segment_grid.setColumnStretch(3, 2)

            self.segments_layout.addWidget(segment_widget)
            
    def on_segment_voice_changed(self, index):
        """Stores the voice change in the segment data structure."""
        voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{index}")
        if voice_combo:
            self.segment_data[index]["voice"] = voice_combo.currentData()

    def play_voice_preview(self):
        """Dynamically generates and plays preview of selected voice, or plays from cache."""
        voice_name = self.gemini_voice_combo.currentData()
        
        # Check if we already have it in persistent cache (VOICES_DIR)
        os.makedirs(VOICES_DIR, exist_ok=True)
        preview_path = os.path.join(VOICES_DIR, f"{voice_name.lower()}_preview.wav")

        # Handle playing / stopping logic
        current_source_path = ""
        if self.player.source().isLocalFile():
            current_source_path = self.player.source().toLocalFile()

        is_playing_this_preview = (
            os.path.exists(preview_path) and
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and
            os.path.normpath(current_source_path) == os.path.normpath(preview_path)
        )

        if is_playing_this_preview:
            self.player.stop()
            print(f"[INFO] Voice preview playback stopped for voice: {voice_name}.")
            self.status_bar.showMessage("Preview playback stopped.")
            return

        if os.path.exists(preview_path):
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(preview_path))
            self.player.play()
            print(f"[INFO] Playing local cached voice preview for: {voice_name}...")
            self.status_bar.showMessage("Playing local voice preview: {0}...".format(voice_name))
            return

        # If we need to generate:
        if not GEMINI_API_KEY:
            self.show_error_message("Gemini API key not found.\n\nSet it in menu 'Tools' -> 'Set API Key...'.")
            return

        if self.active_preview_thread and self.active_preview_thread.is_alive():
            self.status_bar.showMessage("Generating...")
            return

        self.voice_preview_button.setEnabled(False)
        self.voice_preview_button.setText("Generating...")
        print(f"[INFO] Voice preview cache not found. Generating preview for: {voice_name}...")
        self.status_bar.showMessage("Generating voice preview: {0}...".format(voice_name))

        # Dynamic text based on language
        preview_text = "Hello, this is a preview of my voice. I am ready to read your text."

        selected_model_display_name = self.gemini_model_combo.currentText()
        selected_model = GEMINI_TTS_MODELS.get(selected_model_display_name, list(GEMINI_TTS_MODELS.values())[0])
        language_display_name = self.language_combo.currentText()
        language_code = SUPPORTED_LANGUAGES.get(language_display_name, "en-US")
        speaking_rate = self.speed_slider.value() / 100.0

        params = {
            "text": preview_text,
            "prompt": "",
            "voice_name": voice_name,
            "temperature": 1.0,
            "model": selected_model,
            "language_code": language_code,
            "speaking_rate": speaking_rate,
        }

        signals = WorkerSignals()
        signals.finished.connect(lambda result, v=voice_name: self.on_preview_generated(result, v))
        signals.error.connect(self.on_preview_error)

        worker = GeminiWorker(params, signals)
        self.active_preview_thread = Thread(target=worker.run, daemon=True)
        self.active_preview_thread.start()

    def on_preview_generated(self, result, voice_name):
        audio_content = result["audio_content"]
        
        os.makedirs(VOICES_DIR, exist_ok=True)
        audio_path = os.path.join(VOICES_DIR, f"{voice_name.lower()}_preview.wav")
        
        try:
            with open(audio_path, "wb") as f:
                f.write(audio_content)
        except Exception as e:
            print(f"[ERROR] Failed to save voice preview for {voice_name}: {e}")
            self.show_error_message("Error saving preview: {0}".format(e))
            self.voice_preview_button.setEnabled(True)
            self.voice_preview_button.setText("🔊 Preview")
            return
            
        self.voice_preview_button.setEnabled(True)
        self.voice_preview_button.setText("🔊 Preview")
        
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(audio_path))
        self.player.play()
        print(f"[SUCCESS] Voice preview successfully generated and cached for voice: {voice_name}.")
        self.status_bar.showMessage("Playing local voice preview: {0}...".format(voice_name))

    def on_preview_error(self, error_msg):
        self.voice_preview_button.setEnabled(True)
        self.voice_preview_button.setText("🔊 Preview")
        print(f"[ERROR] Voice preview generation failed: {error_msg}")
        self.show_error_message("Error generating voice preview:\n{0}".format(error_msg))
        self.status_bar.showMessage("Error generating voice preview.")

    # REMOVED: Methods on_preview_download_finished and on_preview_download_error

    def play_segment_audio(self, index: int):
        """Plays or stops audio of the selected segment."""
        audio_path = self.segment_data[index].get("audio_temp_path")
        if not audio_path:
            self.show_error_message("Audio for this segment has not been generated.")
            return

        current_source_path = ""
        if self.player.source().isLocalFile():
            current_source_path = self.player.source().toLocalFile()

        # FIX: Using os.path.normpath for reliable comparison of paths
        is_playing_this = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and
            os.path.normpath(current_source_path) == os.path.normpath(audio_path)
        )

        if is_playing_this:
            self.player.stop()
            print(f"[INFO] Stopped audio playback for segment {index + 1}.")
        else:
            self.player.stop() # Stop whatever is currently playing first
            self.player.setSource(QUrl.fromLocalFile(audio_path))
            self.player.play()
            print(f"[INFO] Playing audio for segment {index + 1}...")
            self.status_bar.showMessage("Playing segment {0}...".format(index + 1))

    def merge_segments_audio(self):
        if not self.segment_data: return
        audio_chunks = [s.get("audio") for s in self.segment_data]
        if any(chunk is None for chunk in audio_chunks):
            self.show_error_message("Not all segments have generated audio.")
            return

        print("[INFO] Starting audio segments merge...")
        self.set_ui_enabled(False)
        try:
            all_frames, sample_rate, nchannels, sampwidth = [], -1, -1, -1
            for i, chunk in enumerate(audio_chunks):
                with wave.open(io.BytesIO(chunk), 'rb') as raw:
                    if sample_rate == -1:
                        sample_rate, nchannels, sampwidth = raw.getframerate(), raw.getnchannels(), raw.getsampwidth()
                    elif (raw.getframerate() != sample_rate or raw.getnchannels() != nchannels or raw.getsampwidth() != sampwidth):
                        raise ValueError(f"Segment {i+1} has inconsistent audio parameters.")
                    all_frames.append(raw.readframes(raw.getnframes()))

            output_wav_buffer = io.BytesIO()
            with wave.open(output_wav_buffer, 'wb') as out_wav:
                out_wav.setnchannels(nchannels); out_wav.setsampwidth(sampwidth); out_wav.setframerate(sample_rate)
                out_wav.writeframes(b''.join(all_frames))

            merged_audio_data = output_wav_buffer.getvalue()
            self.audio_content = merged_audio_data
            self.full_audio_temp_path = self.temp_file_manager.create_temp_file(".wav", merged_audio_data)

            png_data = create_waveform_png_data(merged_audio_data, width=1000, height=100)
            png_path = self.temp_file_manager.create_temp_file(".png", png_data)
            self.update_full_waveform(png_path)

            self.play_full_button.setEnabled(True)
            self.save_full_button.setEnabled(True)
            self.merge_segments_button.setEnabled(False)
            print("[SUCCESS] Audio segments merged successfully.")
            self.status_bar.showMessage("Segments merged successfully!")
        except Exception as e:
            print(f"[ERROR] Failed to merge audio segments: {e}")
            self.show_error_message("Error merging audio segments: {0}".format(e))
        finally:
            self.set_ui_enabled(True)


    def media_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.show_error_message("Player error: {0}".format(error_string))
            self.status_bar.showMessage("Player error.")
            self.set_ui_enabled(True)

    def play_full_audio(self):
        if not self.full_audio_temp_path or not self.audio_content:
            return

        current_source_is_local = self.player.source().isLocalFile()
        current_source_path = self.player.source().toLocalFile() if current_source_is_local else None
        is_playing_full = (current_source_path == self.full_audio_temp_path and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

        if is_playing_full:
            self.player.stop()
            print("[INFO] Stopped playing full merged audio.")
        else:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(self.full_audio_temp_path))
            self.player.play()
            print("[INFO] Playing final merged audio...")
            self.status_bar.showMessage("Playing final audio...")

    def stop_all_audio(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()
            print("[INFO] Audio playback stopped.")
            self.status_bar.showMessage("Playback stopped.")
        if not (self.batch_thread and self.batch_thread.isRunning()):
            self.set_ui_enabled(True)

    def save_audio(self):
        if not self.audio_content:
            self.show_error_message("No audio to save. Merge segments first.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Audio File", "gemini_output.wav", "Audio Files (*.wav *.mp3);;WAV Audio Files (*.wav);;MP3 Audio Files (*.mp3)")
        if file_path:
            try:
                print(f"[INFO] Exporting final audio to: {file_path}...")
                if file_path.lower().endswith(".mp3"):
                    if AudioSegment is None:
                        self.show_error_message("To save to MP3, you need to install the pydub library and FFmpeg.\nOpen terminal and run: pip install pydub")
                        return
                    audio = AudioSegment.from_wav(io.BytesIO(self.audio_content))
                    audio.export(file_path, format="mp3", bitrate="192k")
                else:
                    with open(file_path, "wb") as out:
                        out.write(self.audio_content)
                print(f"[SUCCESS] Audio successfully exported to: {file_path}.")
                self.status_bar.showMessage("File saved successfully: {0}".format(file_path))
            except Exception as e:
                print(f"[ERROR] Failed to save audio file to {file_path}: {e}")
                self.show_error_message("Error saving file: {0}".format(e))

    # --- ENHANCED: Granular UI control for multitasking ---
    def set_segment_ui_enabled(self, index: int, enabled: bool):
        """Enables/disables UI elements for ONE segment."""
        gen_button = self.segments_container.findChild(QPushButton, f"gen_button_{index}")
        silence_button = self.segments_container.findChild(QPushButton, f"silence_button_{index}")
        delete_button = self.segments_container.findChild(QPushButton, f"delete_button_{index}")
        text_widget = self.segment_data[index].get("text_widget")
        voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{index}")

        if gen_button:
            gen_button.setEnabled(enabled)
            # Check if generation is running (just in case)
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                 gen_button.setText("⏳...")
            else:
                 gen_button.setText("🔊 Generate" if enabled else "⏳...")
                 
        if silence_button: silence_button.setEnabled(enabled)
        if delete_button: delete_button.setEnabled(enabled)
        if text_widget: text_widget.setEnabled(enabled)
        if voice_combo: voice_combo.setEnabled(enabled)


    def set_ui_enabled(self, enabled: bool, batch_in_progress: bool = False):
        is_playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

        self.stop_all_button.setEnabled(is_playing or batch_in_progress)

        self.gemini_model_combo.setEnabled(enabled)
        self.gemini_voice_combo.setEnabled(enabled)
        self.voice_preview_button.setEnabled(enabled)
        self.style_prompt_combo.setEnabled(enabled)
        self.style_prompt_input.setEnabled(enabled)
        self.temp_slider.setEnabled(enabled)
        self.segment_count_slider.setEnabled(enabled and not self.use_full_text_checkbox.isChecked())
        self.use_full_text_checkbox.setEnabled(enabled)
        self.text_input.setEnabled(enabled)
        self.import_button.setEnabled(enabled)
        self.split_button.setEnabled(enabled)
        self.add_segment_button.setEnabled(enabled)

        self.generate_all_button.setEnabled(enabled and len(self.segment_data) > 0)
        if enabled:
            self.generate_all_button.setText("Generate ALL Segments")
            try: self.generate_all_button.clicked.disconnect()
            except: pass
            self.generate_all_button.clicked.connect(self.start_batch_generation)

        is_merged = self.audio_content is not None
        can_merge = bool(self.segment_data) and all(s.get("audio") for s in self.segment_data)
        self.merge_segments_button.setEnabled(enabled and can_merge and not is_merged)
        self.play_full_button.setEnabled(enabled and is_merged)
        self.save_full_button.setEnabled(enabled and is_merged)

        for i, data in enumerate(self.segment_data):
            # Check if single-thread is running
            is_single_generating = i in self.active_single_gen_threads and self.active_single_gen_threads[i].is_alive()
            
            # If generating, keep it disabled
            if is_single_generating:
                self.set_segment_ui_enabled(i, False)
                continue
            
            self.set_segment_ui_enabled(i, enabled)
            play_button = self.get_segment_play_button(i)
            if play_button: play_button.setEnabled(enabled and data.get("audio") is not None)
            
            # Move buttons
            up_button = self.segments_container.findChild(QPushButton, f"up_button_{i}")
            down_button = self.segments_container.findChild(QPushButton, f"down_button_{i}")
            if up_button: up_button.setEnabled(enabled and i > 0)
            if down_button: down_button.setEnabled(enabled and i < len(self.segment_data) - 1)


        if batch_in_progress:
            self.set_ui_enabled(False)
            self.generate_all_button.setEnabled(True) # Cancel button must remain active
            self.stop_all_button.setEnabled(True)

    def closeEvent(self, event):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
             self.player.stop()
        if self.batch_thread and self.batch_thread.isRunning():
             self.batch_worker.cancel()
             self.batch_thread.quit()
             self.batch_thread.wait()
        # Daemon threads will terminate automatically on process exit
        self.temp_file_manager.cleanup()
        event.accept()

    def show_error_message(self, message):
        msg_box = QMessageBox(self)
        msg_box.setStyleSheet("background-color: #3c3c3c; color: #f0f0f0;")
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setText(str(message))
        msg_box.setWindowTitle("Error")
        msg_box.exec()
        
    # --- NEW FUNCTIONS ---

    def toggle_segmentation_controls(self):
        """Toggles segmentation control elements based on checkbox state."""
        is_checked = self.use_full_text_checkbox.isChecked()
        self.segment_count_slider.setEnabled(not is_checked)
        self.segment_count_label.setEnabled(not is_checked)
        if is_checked:
            self.split_button.setText("Create single segment")
            self.split_button.setToolTip("Creates one segment from the entire main text.")
            self.generate_all_button.setEnabled(True)
        else:
            self.split_button.setText("Split text into segments")
            # Update tooltip based on current slider value
            self.update_split_button_on_slider_change(self.segment_count_slider.value())
            self.generate_all_button.setEnabled(len(self.segment_data) > 0)
            
    def update_split_button_on_slider_change(self, value):
        """Updates label and tooltip when slider value changes."""
        self.segment_count_label.setText(f"Sentences/Seg.: {value}")
        # Only change tooltip if single segment checkbox is not checked
        if not self.use_full_text_checkbox.isChecked():
             self.split_button.setToolTip(f"Splits the main text into segments of {value} sentences.")

    def update_char_count_labels(self):
        """Updates character counts in status bar."""
        self.pro_char_label.setText(f"Pro Chars: {self.pro_char_count}")
        self.flash_char_label.setText(f"Flash Chars: {self.flash_char_count}")
        self.tokens_label.setText(f"In/Out Tokens: {self.in_tokens_count}/{self.out_tokens_count}")
        self.cost_label.setText(f"Cost: ${self.total_cost:.6f}")

    def generate_silence_wav(self, duration_s: int, sample_rate: int = 24000, bits_per_sample: int = 16) -> bytes:
        """Generates WAV data for silence of specified duration."""
        num_channels = 1
        bytes_per_sample = bits_per_sample // 8
        num_frames = int(duration_s * sample_rate)
        
        # Silent data (zero bytes)
        audio_data = b'\x00' * (num_frames * num_channels * bytes_per_sample)
        
        output_buffer = io.BytesIO()
        with wave.open(output_buffer, 'wb') as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(bytes_per_sample)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data)
        
        return output_buffer.getvalue()

    def add_silence_to_segment(self, index: int):
        """Shows dialog and inserts silence into segment."""
        duration, ok = QInputDialog.getInt(self, "Insert Silence", "Enter silence duration in seconds:", 1, 1, 10, 1)
        if ok:
            print(f"[INFO] Inserting {duration} seconds of silence into segment {index + 1}...")
            # Stop playback if currently playing this segment
            if self.player.source().isLocalFile() and self.player.source().toLocalFile() == self.segment_data[index].get("audio_temp_path"):
                self.player.stop()
            
            # If generating, stop it (remove reference)
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                  del self.active_single_gen_threads[index] 
                  self.set_segment_ui_enabled(index, True) # Reset UI

            # Generate silence
            audio_content = self.generate_silence_wav(duration)
            self.segment_data[index]["audio"] = audio_content
            audio_path = self.temp_file_manager.create_temp_file(".wav", audio_content)
            self.segment_data[index]["audio_temp_path"] = audio_path
            
            # Create flat waveform for silence
            png_data = create_waveform_png_data(b'', width=800, height=70) # Empty data generates flat line
            png_path = self.temp_file_manager.create_temp_file(".png", png_data)
            self.segment_data[index]["png_temp_path"] = png_path
            
            # Update UI
            self.update_segment_waveform(index, png_path)
            play_button = self.get_segment_play_button(index)
            play_button.setEnabled(True)
            self.update_segment_play_button_ui(index, QMediaPlayer.PlaybackState.StoppedState)

            can_merge = all(s.get("audio") for s in self.segment_data)
            self.merge_segments_button.setEnabled(can_merge)
            
            print(f"[SUCCESS] Silence of {duration}s inserted into segment {index + 1}.")
            self.status_bar.showMessage(f"Inserted {duration}s silence into segment {index + 1}.")


    def add_new_segment(self):
        """Inserts a new empty segment into list."""
        default_voice = self.gemini_voice_combo.currentData()
        new_segment = {
            "text": "",
            "audio": None,
            "audio_temp_path": None,
            "png_temp_path": None,
            "text_widget": None,
            "voice": default_voice
        }
        self.segment_data.append(new_segment)
        self.display_segments()
        self.generate_all_button.setEnabled(True)
        print(f"[INFO] Inserted a new empty segment at index {len(self.segment_data)}.")
        self.status_bar.showMessage(f"Added new segment. Total: {len(self.segment_data)}.")


    def move_segment_up(self, index: int):
        """Moves segment up by one position."""
        if index > 0:
            print(f"[INFO] Moving segment {index + 1} UP to index {index}...")
            self.segment_data.insert(index - 1, self.segment_data.pop(index))
            self.display_segments()


    def move_segment_down(self, index: int):
        """Moves segment down by one position."""
        if index < len(self.segment_data) - 1:
            print(f"[INFO] Moving segment {index + 1} DOWN to index {index + 2}...")
            self.segment_data.insert(index + 1, self.segment_data.pop(index))
            self.display_segments()


if __name__ == "__main__":
    if sys.platform.startswith('win'):
        QApplication.setStyle("Fusion")
    app = QApplication(sys.argv)
    window = TTS_App()
    window.show()
    sys.exit(app.exec())