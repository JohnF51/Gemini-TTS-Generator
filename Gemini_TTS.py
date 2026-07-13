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
# --- OPRAVA CHYBY: Inicializácia globálnej premennej pred try/except ---
_stanza_pipeline = None

# Importy pre Sentence Splitting (Stanza)
try:
    import stanza
    # Stanza sa bude inicializovať pri prvom volaní
except ImportError:
    print("Upozornenie: Knižnica 'stanza' nebola nájdená. Použije sa jednoduchá segmentácia viet. Pre CZ/SK odporúčame inštaláciu (pip install stanza).")
    stanza = None

# Import pre ukladanie do MP3 (pydub)
try:
    from pydub import AudioSegment
except ImportError:
    print("Upozornenie: Knižnica 'pydub' nebola nájdená. Ukladanie do MP3 nemusí fungovať. Pre ukladanie do MP3 odporúčame inštaláciu (pip install pydub).")
    AudioSegment = None

# --- NOVÝ IMPORT ---
from threading import Thread

# --- NOVÉ: Definovanie koreňového adresára a podadresárov aplikácie ---
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
    """Zašifruje text pomocou Windows DPAPI viazaného na používateľa."""
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
    """Dešifruje text pomocou Windows DPAPI."""
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

# Globálna premenná pre API kľúč, načítava sa neskôr v TTS_App
GEMINI_API_KEY = ""

# --- NOVÉ: Zabezpečenie existencie adresárov pri štarte ---
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
    QSplitter, QTabWidget, QMenu, QInputDialog, QCheckBox, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl, QSize, QMutex, QWaitCondition
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

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

# NOVÁ KONŠTANTA: Pre-definované Style Prompty (SK názov -> EN prompt)
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


# --- VYLEPŠENÉ: Rozšírený zoznam hlasov s informáciou o pohlaví ---
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


# NOVÁ KONŠTANTA: Dostupné TTS modely Gemini
GEMINI_TTS_MODELS = {
    "Gemini 2.5 Pro TTS (Highest quality, style control)": "gemini-2.5-pro-preview-tts",
    "Gemini 2.5 Flash TTS (Lower latency)": "gemini-2.5-flash-preview-tts"
}

# NOVÁ KONŠTANTA: Podporované jazyky (Názov v UI -> Kód pre API)
SUPPORTED_LANGUAGES = {
    "Slovak (SK)": "sk-SK",
    "Czech (CZ)": "cs-CZ",
    "English (US)": "en-US",
    "English (GB)": "en-GB",
    "German (DE)": "de-DE",
    "Spanish (ES)": "es-ES",
    "French (FR)": "fr-FR",
}

# --- UPRAVENÝ Manažér dočasných súborov ---
class TempFileManager:
    """Spravuje dočasný adresár /temp pre WAV a PNG súbory a zabezpečuje jeho vyčistenie."""
    def __init__(self):
        # --- ZMENA: Používa preddefinovaný adresár TEMP_DIR ---
        self.temp_dir = TEMP_DIR
        print(f"Používa sa dočasný adresár: {self.temp_dir}")
        self._temp_files = set() # Množina ciest k dočasným súborom

    def create_temp_file(self, suffix: str, data: bytes = None) -> str:
        """Vytvorí dočasný súbor v spravovanom adresári a vráti jeho cestu."""
        # Používame os.path.join pre multiplatformovú kompatibilitu
        temp_file_path = os.path.join(self.temp_dir, next(tempfile._get_candidate_names()) + suffix)
        if data:
            with open(temp_file_path, "wb") as f:
                f.write(data)
        self._temp_files.add(temp_file_path)
        return temp_file_path

    def cleanup(self):
        """Vymaže obsah dočasného adresára, ale adresár ponechá."""
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
                        print(f"Chyba pri mazaní súboru {file_path}: {e}")
                print(f"Obsah dočasného adresára zmazaný: {self.temp_dir}")
            self._temp_files.clear()
        except Exception as e:
            print(f"Chyba pri čistení dočasného adresára {self.temp_dir}: {e}")

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
            print(f"Kontrolujem/načítavam Stanza model pre '{lang}' do predvoleného adresára (iba tokenizácia)...")
            stanza.download(lang=lang, processors='tokenize', verbose=False)
            _stanza_pipeline = stanza.Pipeline(lang=lang, processors='tokenize', verbose=False)
            print("Stanza pipeline úspešne inicializovaná.")

        except Exception as e:
            print(f"Chyba pri inicializácii Stanza pipeline pre '{lang}', prepínam na fallback: {e}")
            _stanza_pipeline = False

    if _stanza_pipeline is False:
        return False

    return _stanza_pipeline

def _split_text_simple_fallback(text: str, sentences_per_segment: int = 3) -> list[str]:
    """Záložná jednoduchá heuristika na rozdelenie viet."""
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
    Rozdelí text na segmenty po N viet s použitím inteligentnejšej segmentácie (Stanza).
    """
    sentences = []
    stanza_pipe = _init_stanza('cs')

    if stanza_pipe:
        try:
            doc = stanza_pipe(text)
            sentences = [sentence.text.strip() for sentence in doc.sentences if sentence.text.strip()]
        except Exception as e:
            print(f"Chyba pri spracovaní textu cez Stanza, prepínam na fallback: {e}")
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

# --- FUNKCIA PRE VIZUALIZÁCIU WAV ---

def create_waveform_png_data(audio_data: bytes, width: int = 400, height: int = 50) -> bytes:
    """Vykreslí audio dáta (WAV) ako waveform a vráti surové PNG dáta."""

    try:
        if not audio_data:
            return b''

        wav_file = io.BytesIO(audio_data)

        with wave.open(wav_file, 'rb') as raw:
            signal = raw.readframes(-1)
            signal_array = np.frombuffer(signal, dtype=np.int16)
            f_rate = raw.getframerate()

            if len(signal_array) == 0:
                 # NOVÉ: Vykreslí prázdnu (tichú) stopu
                 fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
                 ax = fig.add_subplot(111)
                 ax.plot([0, 1], [0, 0], color='#0095ff', linewidth=0.5)
            else:
                time_arr = np.linspace(0, len(signal_array) / f_rate, num=len(signal_array))

                # Matplotlib nastavenie pre kompaktné PNG
                fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
                ax = fig.add_subplot(111)

                # Zmena farby waveform pre tmavý režim
                ax.plot(time_arr, signal_array, color='#0095ff', linewidth=0.5)

            ax.set_xticks([])
            ax.set_yticks([])
            ax.axis('off')
            ax.margins(0,0)

            # Nastavenie transparentného pozadia fig a ax
            fig.patch.set_alpha(0.0)
            ax.patch.set_alpha(0.0)

            plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

            # Uloženie do pamäte (BytesIO)
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
            buf.seek(0)

            plt.close(fig)

            return buf.read()

    except Exception as e:
        print(f"Chyba pri generovaní waveform: {e}")
        return b''

# ODSTRÁNENÝ WORKER: PreviewDownloader bol nahradený lokálnym prehrávaním ---

# --- Worker trieda pre Gemini ---

class GeminiWorker: # <-- ZMENA: Už nededí od QObject
    """Worker pre Gemini TTS (streamované audio), IBA Single-Speaker."""
    
    def __init__(self, params, signals): # <-- ZMENA: Pridaný parameter 'signals'
        super().__init__()
        self.params = params
        self.signals = signals # <-- ZMENA: Uložíme si signály
        self.text = self.params["text"]
        self.prompt = self.params.get("prompt", "")
        self.voice_name = self.params.get("voice_name", "Zephyr")
        self.temperature = self.params.get("temperature", 1.0)
        self.model = self.params.get("model", "gemini-2.5-pro-preview-tts")
        # NOVÉ: Načítanie jazyka a rýchlosti
        self.language_code = self.params.get("language_code", "sk-SK")
        self.speaking_rate = self.params.get("speaking_rate", 1.0)
        self.client = None

    def run(self):
        try:
            # --- PRIDANÉ LOGOVANIE ---
            print(f"\n[INFO] Spúšťam GeminiWorker pre text: '{self.text[:50]}...'")
            print(f"[INFO] Použitý model: {self.model}, Hlas: {self.voice_name}, Jazyk: {self.language_code}")
            print("---DEBUG: Krok 1 - Vytváram klienta...") # <-- PRIDANÝ RIADOK
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            # --- PRIDANÉ LOGOVANIE ---
            print("[INFO] Klient pre Gemini API bol úspešne inicializovaný.")
            print("---DEBUG: Krok 2 - Klient vytvorený, pripravujem dáta...")
                        
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

            # --- PRIDANÉ LOGOVANIE ---
            print("[INFO] Odosielam požiadavku na Gemini API a čakám na streamované dáta...")
            start_time = time.time()

            print("---DEBUG: Krok 3 - Pokúšam sa spojiť s API a streamovať dáta...") # <-- PRIDANÝ RIADOK
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
                #request_options=request_options
            ):
                # --- PRIDANÉ LOGOVANIE ---
                if not full_audio_data: # Vypíše sa len pri prvom prijatí dát
                    first_chunk_time = time.time()
                    print(f"[INFO] Prijatý prvý chunk dát po {first_chunk_time - start_time:.2f} sekundách.")

                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    in_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', in_tokens) or in_tokens
                    out_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', out_tokens) or out_tokens

                if (
                    chunk.candidates
                    and chunk.candidates[0].content
                    and chunk.candidates[0].content.parts
                    and chunk.candidates[0].content.parts[0].inline_data
                    and chunk.candidates[0].content.parts[0].inline_data.data
                ):
                    inline_data = chunk.candidates[0].content.parts[0].inline_data
                    full_audio_data += inline_data.data
                    if not mime_type:
                        mime_type = inline_data.mime_type

            # --- PRIDANÉ LOGOVANIE ---
            end_time = time.time()
            print(f"[INFO] Streamovanie dokončené. Celkový čas: {end_time - start_time:.2f} sekúnd.")
            print(f"[INFO] Celková veľkosť prijatých audio dát: {len(full_audio_data)} bajtov.")

            if not full_audio_data:
                 print("[ERROR] Generovanie nevrátilo žiadne audio dáta.")
                 self.signals.error.emit(f"Generovanie Gemini TTS nevrátilo žiadne audio dáta. Použitý model: {self.model}") # <-- ZMENA
                 return

            if not mime_type.lower().startswith("audio/wav"):
                # --- PRIDANÉ LOGOVANIE ---
                print(f"[INFO] Prijatý MIME typ '{mime_type}', konvertujem na WAV.")
                full_audio_data = convert_to_wav(full_audio_data, mime_type)
                final_mime_type = "audio/wav"
                print("[INFO] Konverzia na WAV dokončená.")
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
            # --- PRIDANÉ LOGOVANIE ---
            print("[SUCCESS] Worker úspešne dokončil prácu.")
            self.signals.finished.emit(result) # <-- ZMENA

        except GeminiAPIError as e:
             # --- PRIDANÉ LOGOVANIE ---
             print(f"[FATAL ERROR] Chyba pri volaní Gemini API: {e}")
             self.signals.error.emit(f"Chyba pri volaní Gemini API: {e}. Uistite sa, že kľúč je platný a povolenia sú aktívne.") # <-- ZMENA
        except ValueError as e:
            # --- PRIDANÉ LOGOVANIE ---
            print(f"[FATAL ERROR] Chyba konfigurácie pre Gemini: {e}")
            self.signals.error.emit(f"Chyba konfigurácie pre Gemini: {e}") # <-- ZMENA
        except Exception as e:
            # --- PRIDANÉ LOGOVANIE ---
            print(f"[FATAL ERROR] Neznáma chyba v GeminiWorker: {e}")
            self.signals.error.emit(f"Neznáma chyba (Gemini TTS): {e}") # <-- ZMENA

# --- Worker trieda pre DÁVKOVÚ GENERÁCIU ---

class SegmentBatchWorker(QObject):
    """Worker, ktorý postupne generuje segmenty."""

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
        # NOVÉ: Uloženie jazyka a rýchlosti
        self.language_code = language_code
        self.speaking_rate = speaking_rate
        self._is_cancelled = False

    def cancel(self):
        """Zruší aktuálnu dávkovú operáciu."""
        self._is_cancelled = True

    def run(self):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            i = -1 # Pre prípad chyby ešte pred slučkou

            for i, segment_info in enumerate(self.segments_to_process):
                if self._is_cancelled:
                    self.status_update.emit(f"Dávkové generovanie zrušené užívateľom (Segment {i+1}/{len(self.segments_to_process)}).")
                    break
                
                text = segment_info["text"]
                voice_name = segment_info["voice"] # --- VYLEPŠENÉ: Hlas pre každý segment ---

                self.status_update.emit(f"Generujem reč (Segment {i+1}/{len(self.segments_to_process)}), prosím čakajte...")

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
                
                # UPRAVENÉ: Pridanie jazyka a rýchlosti do konfigurácie
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

                for chunk in client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=generate_content_config,
                    #request_options=request_options
                ):
                    if self._is_cancelled:
                        self.status_update.emit(f"Dávkové generovanie zrušené (Segment {i+1}).")
                        return

                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        in_tokens = getattr(chunk.usage_metadata, 'prompt_token_count', in_tokens) or in_tokens
                        out_tokens = getattr(chunk.usage_metadata, 'candidates_token_count', out_tokens) or out_tokens

                    if (
                        chunk.candidates
                        and chunk.candidates[0].content
                        and chunk.candidates[0].content.parts
                        and chunk.candidates[0].content.parts[0].inline_data
                        and chunk.candidates[0].content.parts[0].inline_data.data
                    ):
                        inline_data = chunk.candidates[0].content.parts[0].inline_data
                        full_audio_data += inline_data.data
                        if not mime_type:
                            mime_type = inline_data.mime_type

                if not full_audio_data:
                    raise Exception(f"Generovanie segmentu {i+1} nevrátilo žiadne audio dáta.")

                if not mime_type.lower().startswith("audio/wav"):
                    audio_content = convert_to_wav(full_audio_data, mime_type)
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
                # Vrátime pôvodný index zo `segment_data`
                self.segment_generated.emit(segment_info["original_index"], result)


            if not self._is_cancelled:
                self.finished.emit()

        except GeminiAPIError as e:
             self.error.emit(f"Chyba pri volaní Gemini API v dávke: {e}.")
        except Exception as e:
            segment_num_str = f" (Segment {i+1})" if i != -1 else ""
            self.error.emit(f"Neznáma chyba v dávkovom generovaní{segment_num_str}: {e}")

# --- NOVÁ POMOCNÁ TRIEDA PRE SIGNÁLY (bod 1) ---
class WorkerSignals(QObject):
    """
    Definuje signály dostupné z 'robotníckeho' vlákna.
    - finished: signál po úspešnom dokončení
    - error: signál v prípade chyby
    """
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

# --- NOVÁ TRIEDA PRE DYNAMICKÉ NAČÍTANIE MODELOV ---
class ModelFetchWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            if not GEMINI_API_KEY:
                self.error.emit("Chýba API kľúč.")
                return
            client = genai.Client(api_key=GEMINI_API_KEY)
            tts_models = {}
            # Prejdeme dostupné modely
            for m in client.models.list():
                name = m.name
                # Modely pre prevod textu na reč obsahujú 'tts'
                if "tts" in name.lower():
                    display_name = getattr(m, 'display_name', None)
                    if not display_name:
                        # Ak nie je display_name, použijeme aspoň formátovaný názov
                        display_name = name.replace("models/", "").replace("-", " ").title()
                    else:
                        # Pridáme aj info o tom, či je to free/pay ak to z názvu nevyplýva priamo,
                        # ale API to zatiaľ nevracia štandardizovane. Zobrazíme display_name.
                        pass
                    tts_models[display_name] = name.replace("models/", "")
            
            if tts_models:
                self.finished.emit(tts_models)
            else:
                self.error.emit("Žiadne TTS modely.")
        except Exception as e:
            self.error.emit(str(e))

# --- NOVÉ: PREKLADY UI ---
TRANSLATIONS = {
    "sk": {},
    "cz": {
        "1. Vstup a Nastavenia": "1. Vstup a Nastavení",
        "Hlavný textový vstup": "Hlavní textový vstup",
        "Vložte sem váš text na prevod na reč...": "Vložte sem váš text pro převod na řeč...",
        "Predvolené nastavenia generovania": "Výchozí nastavení generování",
        "TTS Model:": "TTS Model:",
        "Predvolený Hlas:": "Výchozí Hlas:",
        "🔊 Ukážka": "🔊 Ukázka",
        "Jazyk:": "Jazyk:",
        "Štýl (predvoľba):": "Styl (předvolba):",
        "Prompt (EN):": "Prompt (EN):",
        "Vlastný 'Style Prompt' v angličtine...": "Vlastní 'Style Prompt' v angličtině...",
        "Rýchlosť Reči:": "Rychlost Řeči:",
        "Teplota:": "Teplota:",
        "Ovládanie segmentácie a generovania": "Ovládání segmentace a generování",
        "Použiť celý text ako jeden segment": "Použít celý text jako jeden segment",
        "Viet/Segment:": "Vět/Segment:",
        "✂ Rozdeliť text na segmenty": "✂ Rozdělit text na segmenty",
        "🚀 Generovať VŠETKY Segmenty": "🚀 Generovat VŠECHNY Segmenty",
        "2. Editor Segmentov": "2. Editor Segmentů",
        "Segmenty": "Segmenty",
        "➕ Vložiť Prázdny Segment": "➕ Vložit Prázdný Segment",
        "3. Finálny Výstup": "3. Finální Výstup",
        "Finálny výstup": "Finální výstup",
        "Krivka: Zlúčte segmenty...": "Křivka: Slučte segmenty...",
        "Krivka: Zlúčte segmenty pre zobrazenie celkovej waveform.": "Křivka: Slučte segmenty pro zobrazení celkové waveform.",
        "➕ Zlúčiť Segmenty": "➕ Sloučit Segmenty",
        "▶ Prehrať Celok": "▶ Přehrát Celek",
        "💾 Uložiť WAV": "💾 Uložit WAV",
        "◼ STOP": "◼ STOP",
        "◼ Zastaviť Celok": "◼ Zastavit Celek",
        "Aplikácia pripravená.": "Aplikace připravena.",
        "Súbor": "Soubor",
        "Nový Projekt": "Nový Projekt",
        "Načítať Projekt...": "Načíst Projekt...",
        "Uložiť Projekt...": "Uložit Projekt...",
        "Uložiť Celý WAV...": "Uložit Celý WAV...",
        "Ukončiť": "Ukončit",
        "Nástroje": "Nástroje",
        "Vyčistiť dočasné súbory": "Vyčistit dočasné soubory",
        "Pomoc": "Nápověda",
        "O programe": "O programu",
        "Jazyk / Language": "Jazyk / Language",
        "Slovenčina (SK)": "Slovenština (SK)",
        "Čeština (CZ)": "Čeština (CZ)",
        "Angličtina (EN)": "Angličtina (EN)",
        "Krivka nevygenerovaná": "Křivka nevygenerována",
        "Generuje sa...": "Generuje se...",
        "Čaká sa...": "Čeká se...",
        "Generovanie ZLYHALO.": "Generování SELHALO.",
        "🏷️ Vložiť Tag": "🏷️ Vložit Tag",
        "🔊 Generovať": "🔊 Generovat",
        "▶ Prehrať": "▶ Přehrát",
        "◼ Zastaviť": "◼ Zastavit",
        "🔇 Ticho": "🔇 Ticho",
        "🗑 Zmazať": "🗑 Smazat",
        "⏳...": "⏳...",
        "Zadajte prosím text na spracovanie.": "Zadejte prosím text ke zpracování.",
        "Text nebolo možné spracovať na segmenty.": "Text nebylo možné zpracovat na segmenty.",
        "Vytvorený 1 segment z celého textu.": "Vytvořen 1 segment z celého textu.",
        "Text rozdelený na {0} segmentov.": "Text rozdělen na {0} segmentů.",
        "Pridaný nový segment. Celkovo: {0}.": "Přidán nový segment. Celkovo: {0}.",
        "Segment zmazaný. Ostáva {0} segmentov.": "Segment smazán. Zbývá {0} segmentů.",
        "Nie všetky segmenty majú vygenerované audio.": "Ne všechny segmenty mají vygenerované audio.",
        "Segmenty úspešne zlúčené!": "Segmenty úspěšně sloučeny!",
        "Chyba pri zlúčení audio segmentov: {0}": "Chyba při sloučení audio segmentů: {0}",
        "Žiadny zvuk na uloženie. Najprv zlúčte segmenty.": "Žádný zvuk k uložení. Nejprve slučte segmenty.",
        "Prehrávanie zastavené.": "Přehrávání zastaveno.",
        "Prehrávam finálny zvuk...": "Přehrávám finální zvuk...",
        "Súbor úspešne uložený: {0}": "Soubor úspěšně uložen: {0}",
        "Vytvorený nový projekt.": "Vytvořen nový projekt.",
        "Projekt úspešne uložený do: {0}": "Projekt úspěšně uložen do: {0}",
        "Projekt načítaný s {0} segmentmi.": "Projekt načten s {0} segmenty.",
        "Projekt načítaný. Rozdeľte text na segmenty.": "Projekt načten. Rozdělte text na segmenty.",
        "Aktuálne TTS modely úspešne načítané z Gemini API.": "Aktuální TTS modely úspěšně načteny z Gemini API.",
        "Načítavam aktuálne modely z API...": "Načítám aktuální modely z API...",
        "Nepodarilo sa načítať modely, použijú sa predvolené. ({0})": "Nepodařilo se načíst modely, použijí se výchozí. ({0})",
        "Pre hlas '{0}' nebola nájdená cesta k ukážke.": "Pro hlas '{0}' nebyla nalezena cesta k ukázce.",
        "Prehrávanie ukážky zastavené.": "Přehrávání ukázky zastaveno.",
        "Súbor s ukážkou nebol nájdený na ceste:": "Soubor s ukázkou nebyl nalezen na cestě:",
        "Prehrávam lokálnu ukážku hlasu: {0}...": "Přehrávám lokální ukázku hlasu: {0}...",
        "Audio pre tento segment nebolo vygenerované.": "Audio pro tento segment nebylo vygenerováno.",
        "Prehrávam segment {0}...": "Přehrávám segment {0}...",
        "Gemini API kľúč nebol nájdený.": "Gemini API klíč nebyl nalezen.",
        "Prebieha dávkové generovanie. Zrušte ho, ak chcete generovať iba jeden segment.": "Probíhá dávkové generování. Zrušte ho, pokud chcete generovat pouze jeden segment.",
        "Segment neobsahuje text na generovanie.": "Segment neobsahuje text pro generování.",
        "Generujem reč (Segment {0})...": "Generuji řeč (Segment {0})...",
        "Segment {0} vygenerovaný.": "Segment {0} vygenerován.",
        "Počas generovania segmentu {0} nastala chyba.": "Během generování segmentu {0} nastala chyba.",
        "Chyba pri generovaní segmentu {0}:\n{1}": "Chyba při generování segmentu {0}:\n{1}",
        "Prebieha generovanie jednotlivých segmentov. Dávkové generovanie nie je možné spustiť.": "Probíhá generování jednotlivých segmentů. Dávkové generování nelze spustit.",
        "Všetky segmenty už majú vygenerované audio alebo sú prázdne.": "Všechny segmenty již mají vygenerované audio nebo jsou prázdné.",
        "Spúšťam dávkové generovanie {0} segmentov...": "Spouštím dávkové generování {0} segmentů...",
        "Ruším generovanie...": "Ruším generování...",
        "Dávkové generovanie dokončené! Audio automaticky zlúčené.": "Dávkové generování dokončeno! Audio automaticky sloučeno.",
        "Dávkové generovanie zrušené.": "Dávkové generování zrušeno.",
        "Chyba dávkového generovania: {0}": "Chyba dávkového generování: {0}",
        "Chyba: Dávkové generovanie zlyhalo.": "Chyba: Dávkové generování selhalo.",
        "📝 Vytvoriť jeden segment": "📝 Vytvořit jeden segment",
        "Zadajte dĺžku ticha v sekundách:": "Zadejte délku ticha v sekundách:",
        "Vložiť Ticho": "Vložit Ticho",
        "Do segmentu {0} vložené {1}s ticho.": "Do segmentu {0} vloženo {1}s ticho.",
        "Chyba prehrávača: {0}": "Chyba přehrávače: {0}",
        "Chyba prehrávača.": "Chyba přehrávače.",
    },
    "en": {
        "1. Vstup a Nastavenia": "1. Input & Settings",
        "Hlavný textový vstup": "Main Text Input",
        "Vložte sem váš text na prevod na reč...": "Paste your text for text-to-speech here...",
        "Predvolené nastavenia generovania": "Default Generation Settings",
        "TTS Model:": "TTS Model:",
        "Predvolený Hlas:": "Default Voice:",
        "🔊 Ukážka": "🔊 Preview",
        "Jazyk:": "Language:",
        "Štýl (predvoľba):": "Style (preset):",
        "Prompt (EN):": "Prompt (EN):",
        "Vlastný 'Style Prompt' v angličtine...": "Custom 'Style Prompt' in English...",
        "Rýchlosť Reči:": "Speech Rate:",
        "Teplota:": "Temperature:",
        "Ovládanie segmentácie a generovania": "Segmentation and Generation Control",
        "Použiť celý text ako jeden segment": "Use full text as one segment",
        "Viet/Segment:": "Sentences/Seg.:",
        "✂ Rozdeliť text na segmenty": "✂ Split text into segments",
        "🚀 Generovať VŠETKY Segmenty": "🚀 Generate ALL Segments",
        "2. Editor Segmentov": "2. Segments Editor",
        "Segmenty": "Segments",
        "➕ Vložiť Prázdny Segment": "➕ Add Empty Segment",
        "3. Finálny Výstup": "3. Final Output",
        "Finálny výstup": "Final output",
        "Krivka: Zlúčte segmenty...": "Waveform: Merge segments...",
        "Krivka: Zlúčte segmenty pre zobrazenie celkovej waveform.": "Waveform: Merge segments to view full waveform.",
        "➕ Zlúčiť Segmenty": "➕ Merge Segments",
        "▶ Prehrať Celok": "▶ Play Full",
        "💾 Uložiť WAV": "💾 Save WAV",
        "◼ STOP": "◼ STOP",
        "◼ Zastaviť Celok": "◼ Stop Full",
        "Aplikácia pripravená.": "Application ready.",
        "Súbor": "File",
        "Nový Projekt": "New Project",
        "Načítať Projekt...": "Load Project...",
        "Uložiť Projekt...": "Save Project...",
        "Uložiť Celý WAV...": "Save Full WAV...",
        "Ukončiť": "Exit",
        "Nástroje": "Tools",
        "Vyčistiť dočasné súbory": "Clear temporary files",
        "Pomoc": "Help",
        "O programe": "About",
        "Jazyk / Language": "Jazyk / Language",
        "Slovenčina (SK)": "Slovak (SK)",
        "Čeština (CZ)": "Czech (CZ)",
        "Angličtina (EN)": "English (EN)",
        "Krivka nevygenerovaná": "Waveform not generated",
        "Generuje sa...": "Generating...",
        "Čaká sa...": "Waiting...",
        "Generovanie ZLYHALO.": "Generation FAILED.",
        "🏷️ Vložiť Tag": "🏷️ Insert Tag",
        "🔊 Generovať": "🔊 Generate",
        "▶ Prehrať": "▶ Play",
        "◼ Zastaviť": "◼ Stop",
        "🔇 Ticho": "🔇 Silence",
        "🗑 Zmazať": "🗑 Delete",
        "⏳...": "⏳...",
        "Zadajte prosím text na spracovanie.": "Please enter text to process.",
        "Text nebolo možné spracovať na segmenty.": "Could not process text into segments.",
        "Vytvorený 1 segment z celého textu.": "Created 1 segment from the full text.",
        "Text rozdelený na {0} segmentov.": "Text split into {0} segments.",
        "Pridaný nový segment. Celkovo: {0}.": "Added new segment. Total: {0}.",
        "Segment zmazaný. Ostáva {0} segmentov.": "Segment deleted. {0} segments remaining.",
        "Nie všetky segmenty majú vygenerované audio.": "Not all segments have generated audio.",
        "Segmenty úspešne zlúčené!": "Segments merged successfully!",
        "Chyba pri zlúčení audio segmentov: {0}": "Error merging audio segments: {0}",
        "Žiadny zvuk na uloženie. Najprv zlúčte segmenty.": "No audio to save. Merge segments first.",
        "Prehrávanie zastavené.": "Playback stopped.",
        "Prehrávam finálny zvuk...": "Playing final audio...",
        "Súbor úspešne uložený: {0}": "File saved successfully: {0}",
        "Vytvorený nový projekt.": "New project created.",
        "Projekt úspešne uložený do: {0}": "Project saved successfully to: {0}",
        "Projekt načítaný s {0} segmentmi.": "Project loaded with {0} segments.",
        "Projekt načítaný. Rozdeľte text na segmenty.": "Project loaded. Split text into segments.",
        "Aktuálne TTS modely úspešne načítané z Gemini API.": "Current TTS models successfully loaded from Gemini API.",
        "Načítavam aktuálne modely z API...": "Loading current models from API...",
        "Nepodarilo sa načítať modely, použijú sa predvolené. ({0})": "Failed to load models, using defaults. ({0})",
        "Pre hlas '{0}' nebola nájdená cesta k ukážke.": "Preview path not found for voice '{0}'.",
        "Prehrávanie ukážky zastavené.": "Preview playback stopped.",
        "Súbor s ukážkou nebol nájdený na ceste:": "Preview file not found at path:",
        "Prehrávam lokálnu ukážku hlasu: {0}...": "Playing local voice preview: {0}...",
        "Audio pre tento segment nebolo vygenerované.": "Audio for this segment has not been generated.",
        "Prehrávam segment {0}...": "Playing segment {0}...",
        "Gemini API kľúč nebol nájdený.": "Gemini API key not found.",
        "Prebieha dávkové generovanie. Zrušte ho, ak chcete generovať iba jeden segment.": "Batch generation in progress. Cancel it to generate a single segment.",
        "Segment neobsahuje text na generovanie.": "Segment contains no text to generate.",
        "Generujem reč (Segment {0})...": "Generating speech (Segment {0})...",
        "Segment {0} vygenerovaný.": "Segment {0} generated.",
        "Počas generovania segmentu {0} nastala chyba.": "Error occurred during generation of segment {0}.",
        "Chyba pri generovaní segmentu {0}:\n{1}": "Error generating segment {0}:\n{1}",
        "Prebieha generovanie jednotlivých segmentov. Dávkové generovanie nie je možné spustiť.": "Individual segments are generating. Batch generation cannot be started.",
        "Všetky segmenty už majú vygenerované audio alebo sú prázdne.": "All segments already have audio generated or are empty.",
        "Spúšťam dávkové generovanie {0} segmentov...": "Starting batch generation of {0} segments...",
        "Ruším generovanie...": "Canceling generation...",
        "Dávkové generovanie dokončené! Audio automaticky zlúčené.": "Batch generation complete! Audio merged automatically.",
        "Dávkové generovanie zrušené.": "Batch generation canceled.",
        "Chyba dávkového generovania: {0}": "Batch generation error: {0}",
        "Chyba: Dávkové generovanie zlyhalo.": "Error: Batch generation failed.",
        "📝 Vytvoriť jeden segment": "📝 Create single segment",
        "Zadajte dĺžku ticha v sekundách:": "Enter silence duration in seconds:",
        "Vložiť Ticho": "Insert Silence",
        "Do segmentu {0} vložené {1}s ticho.": "Inserted {1}s silence into segment {0}.",
        "Chyba prehrávača: {0}": "Player error: {0}",
        "Chyba prehrávača.": "Player error.",
    }
}

# --- Hlavná trieda aplikácie ---

class CustomTextEdit(QTextEdit):
    """Rozšírený QTextEdit pre sledovanie zamerania (Focus In)."""
    focus_in_signal = pyqtSignal(object)

    def focusInEvent(self, event):
        """Preťaženie udalosti pri získaní focusu."""
        super().focusInEvent(event)
        self.focus_in_signal.emit(self)


class TTS_App(QMainWindow):
    def __init__(self):
        super().__init__()

        self.temp_file_manager = TempFileManager()
        self.active_text_widget = None
        self.audio_content = None
        self.full_audio_temp_path = None
        self.segment_data = []

        # --- NOVÉ: Konfigurácia jazyka a cien ---
        self.config_path = os.path.join(APP_ROOT, "settings.json")
        self.current_lang = "sk"
        self.pro_rate = 0.0
        self.flash_rate = 0.0
        self.in_tokens_count = 0
        self.out_tokens_count = 0
        self.total_cost = 0.0
        self.load_settings()

        # --- VYLEPŠENÉ: Počítadlá znakov ---
        self.pro_char_count = 0
        self.flash_char_count = 0

        # Workery pre generovanie
        self.current_worker = None
        self.current_thread = None
        self.batch_worker: SegmentBatchWorker | None = None
        self.batch_thread: QThread | None = None
        
        # --- VYLEPŠENÉ: Sledovanie bežiacich generátorov pre multitasking ---
        # ZMENA: Prechádzame na threading.Thread, active_single_gen_threads už nie je nutné
        self.active_single_gen_threads = {} # {index: Thread}

        # NOVÉ: Sledovanie pre dynamické generovanie ukážky hlasu (trvalá cache vo VOICES_DIR)
        self.active_preview_thread = None

        # Prehrávač
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self.update_play_button_state)
        self.player.errorOccurred.connect(self.media_player_error)

        self.init_ui()
        self.populate_gemini_voices()
        self.fetch_dynamic_models()

        self.setWindowTitle("Gemini TTS Generator v12 (Multitasking & Enhancements)")
        self.setGeometry(100, 100, 1400, 900)

        self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty pre zobrazenie celkovej waveform."))
        self.full_waveform_label.setPixmap(QPixmap())

        self.gemini_model_combo.setCurrentText(list(GEMINI_TTS_MODELS.keys())[0])
        self.update_char_count_labels()
        self.retranslate_ui() # Inicializačný preklad

    def tr(self, text: str) -> str:
        """Vráti preklad textu podľa aktuálneho jazyka."""
        en_dict = {
            "1. Vstup a Nastavenia": "1. Input & Settings",
            "Hlavný textový vstup": "Main Text Input",
            "Vložte sem váš text na prevod na reč...": "Paste your text for text-to-speech here...",
            "Predvolené nastavenia generovania": "Default Generation Settings",
            "TTS Model:": "TTS Model:",
            "Predvolený Hlas:": "Default Voice:",
            "🔊 Ukážka": "🔊 Preview",
            "Jazyk:": "Language:",
            "Štýl (predvoľba):": "Style (preset):",
            "Prompt (EN):": "Prompt (EN):",
            "Vlastný 'Style Prompt' v angličtine...": "Custom 'Style Prompt' in English...",
            "Rýchlosť Reči:": "Speech Rate:",
            "Teplota:": "Temperature:",
            "Ovládanie segmentácie a generovania": "Segmentation and Generation Control",
            "Použiť celý text ako jeden segment": "Use full text as one segment",
            "Viet/Segment:": "Sentences/Seg.:",
            "✂ Rozdeliť text na segmenty": "✂ Split text into segments",
            "🚀 Generovať VŠETKY Segmenty": "🚀 Generate ALL Segments",
            "2. Editor Segmentov": "2. Segments Editor",
            "Segmenty": "Segments",
            "➕ Vložiť Prázdny Segment": "➕ Add Empty Segment",
            "3. Finálny Výstup": "3. Final Output",
            "Finálny výstup": "Final output",
            "Krivka: Zlúčte segmenty...": "Waveform: Merge segments...",
            "Krivka: Zlúčte segmenty pre zobrazenie celkovej waveform.": "Waveform: Merge segments to view full waveform.",
            "➕ Zlúčiť Segmenty": "➕ Merge Segments",
            "▶ Prehrať Celok": "▶ Play Full",
            "💾 Uložiť WAV": "💾 Save WAV",
            "◼ STOP": "◼ STOP",
            "◼ Zastaviť Celok": "◼ Stop Full",
            "Aplikácia pripravená.": "Application ready.",
            "Súbor": "File",
            "Nový Projekt": "New Project",
            "Načítať Projekt...": "Load Project...",
            "Uložiť Projekt...": "Save Project...",
            "Uložiť Celý WAV...": "Save Full WAV...",
            "Ukončiť": "Exit",
            "Nástroje": "Tools",
            "Vyčistiť dočasné súbory": "Clear temporary files",
            "Pomoc": "Help",
            "O programe": "About",
            "Jazyk / Language": "Jazyk / Language",
            "Slovenčina (SK)": "Slovak (SK)",
            "Čeština (CZ)": "Czech (CZ)",
            "Angličtina (EN)": "English (EN)",
            "Krivka nevygenerovaná": "Waveform not generated",
            "Generuje sa...": "Generating...",
            "Čaká sa...": "Waiting...",
            "Generovanie ZLYHALO.": "Generation FAILED.",
            "🏷️ Vložiť Tag": "🏷️ Insert Tag",
            "🔊 Generovať": "🔊 Generate",
            "▶ Prehrať": "▶ Play",
            "◼ Zastaviť": "◼ Stop",
            "🔇 Ticho": "🔇 Silence",
            "🗑 Zmazať": "🗑 Delete",
            "⏳...": "⏳...",
            "Zadajte prosím text na spracovanie.": "Please enter text to process.",
            "Text nebolo možné spracovať na segmenty.": "Could not process text into segments.",
            "Vytvorený 1 segment z celého textu.": "Created 1 segment from the full text.",
            "Text rozdelený na {0} segmentov.": "Text split into {0} segments.",
            "Pridaný nový segment. Celkovo: {0}.": "Added new segment. Total: {0}.",
            "Segment zmazaný. Ostáva {0} segmentov.": "Segment deleted. {0} segments remaining.",
            "Nie všetky segmenty majú vygenerované audio.": "Not all segments have generated audio.",
            "Segmenty úspešne zlúčené!": "Segments merged successfully!",
            "Chyba pri zlúčení audio segmentov: {0}": "Error merging audio segments: {0}",
            "Žiadny zvuk na uloženie. Najprv zlúčte segmenty.": "No audio to save. Merge segments first.",
            "Prehrávanie zastavené.": "Playback stopped.",
            "Prehrávam finálny zvuk...": "Playing final audio...",
            "Súbor úspešne uložený: {0}": "File saved successfully: {0}",
            "Vytvorený nový projekt.": "New project created.",
            "Projekt úspešne uložený do: {0}": "Project saved successfully to: {0}",
            "Projekt načítaný s {0} segmentmi.": "Project loaded with {0} segments.",
            "Projekt načítaný. Rozdeľte text na segmenty.": "Project loaded. Split text into segments.",
            "Aktuálne TTS modely úspešne načítané z Gemini API.": "Current TTS models successfully loaded from Gemini API.",
            "Načítavam aktuálne modely z API...": "Loading current models from API...",
            "Nepodarilo sa načítať modely, použijú sa predvolené. ({0})": "Failed to load models, using defaults. ({0})",
            "Pre hlas '{0}' nebola nájdená cesta k ukážke.": "Preview path not found for voice '{0}'.",
            "Prehrávanie ukážky zastavené.": "Preview playback stopped.",
            "Súbor s ukážkou nebol nájdený na ceste:": "Preview file not found at path:",
            "Prehrávam lokálnu ukážku hlasu: {0}...": "Playing local voice preview: {0}...",
            "Audio pre tento segment nebolo vygenerované.": "Audio for this segment has not been generated.",
            "Prehrávam segment {0}...": "Playing segment {0}...",
            "Gemini API kľúč nebol nájdený.": "Gemini API key not found.",
            "Prebieha dávkové generovanie. Zrušte ho, ak chcete generovať iba jeden segment.": "Batch generation in progress. Cancel it to generate a single segment.",
            "Segment neobsahuje text na generovanie.": "Segment contains no text to generate.",
            "Generujem reč (Segment {0})...": "Generating speech (Segment {0})...",
            "Segment {0} vygenerovaný.": "Segment {0} generated.",
            "Počas generovania segmentu {0} nastala chyba.": "Error occurred during generation of segment {0}.",
            "Chyba pri generovaní segmentu {0}:\n{1}": "Error generating segment {0}:\n{1}",
            "Prebieha generovanie jednotlivých segmentov. Dávkové generovanie nie je možné spustiť.": "Individual segments are generating. Batch generation cannot be started.",
            "Všetky segmenty už majú vygenerované audio alebo sú prázdne.": "All segments already have audio generated or are empty.",
            "Spúšťam dávkové generovanie {0} segmentov...": "Starting batch generation of {0} segments...",
            "Ruším generovanie...": "Canceling generation...",
            "Dávkové generovanie dokončené! Audio automaticky zlúčené.": "Batch generation complete! Audio merged automatically.",
            "Dávkové generovanie zrušené.": "Batch generation canceled.",
            "Chyba dávkového generovania: {0}": "Batch generation error: {0}",
            "Chyba: Dávkové generovanie zlyhalo.": "Error: Batch generation failed.",
            "📝 Vytvoriť jeden segment": "📝 Create single segment",
            "Zadajte dĺžku ticha v sekundách:": "Enter silence duration in seconds:",
            "Vložiť Ticho": "Insert Silence",
            "Do segmentu {0} vložené {1}s ticho.": "Inserted {1}s silence into segment {0}.",
            "Chyba prehrávača: {0}": "Player error: {0}",
            "Chyba prehrávača.": "Player error.",
            "Nastavenie API kľúča": "API Key Settings",
            "Vložte váš Gemini API kľúč:": "Enter your Gemini API key:",
            "API kľúč bol úspešne uložený.": "API key was successfully saved.",
            "Cenník (Pro)": "Pricing (Pro)",
            "Sadzba za 1 milión tokenov/znakov pre PRO model (v $):": "Rate per 1 million tokens/chars for PRO model (in $):",
            "Cenník (Flash)": "Pricing (Flash)",
            "Sadzba za 1 milión tokenov/znakov pre FLASH model (v $):": "Rate per 1 million tokens/chars for FLASH model (in $):",
            "Sadzby úspešne uložené.": "Rates successfully saved.",
            "Nastaviť API kľúč...": "Set API Key...",
            "Nastaviť sadzby (Cenník)...": "Set Rates (Pricing)..."
        }
        return en_dict.get(text, text)

    def load_settings(self):
        """Načíta nastavenia aplikácie zo súboru."""
        global GEMINI_API_KEY
        
        # 1. Najprv načítame zo settings.json
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.current_lang = config.get("language", "sk")
                    self.pro_rate = config.get("pro_rate", 0.0)
                    self.flash_rate = config.get("flash_rate", 0.0)
                    enc_key = config.get("encrypted_api_key", "")
                    if enc_key:
                        decrypted = decrypt_api_key(enc_key)
                        if decrypted:
                            GEMINI_API_KEY = decrypted
            except Exception as e:
                print(f"Error loading settings: {e}")

        # 2. Migrácia zo starého súboru gemini.txt (ak existuje)
        old_key_path = os.path.join(APP_ROOT, "gemini.txt")
        if os.path.exists(old_key_path):
            try:
                with open(old_key_path, "r", encoding="utf-8") as f:
                    api_key = f.read().strip()
                if api_key:
                    GEMINI_API_KEY = api_key
                    self.save_settings() # Zašifruje a uloží
                    print("INFO: API kľúč úspešne migrovaný zo súboru gemini.txt do settings.json.")
                # Zmazať starý nezabezpečený súbor
                os.remove(old_key_path)
                print("INFO: Súbor gemini.txt bol bezpečne odstránený.")
            except Exception as e:
                print(f"CHYBA pri migrácii gemini.txt: {e}")

    def save_settings(self):
        """Uloží nastavenia aplikácie do súboru."""
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

    def change_language(self, lang_code):
        """Zmení jazyk aplikácie a aktualizuje UI. (Odstránené)"""
        pass

    def retranslate_ui(self):
        """Aktualizuje všetky statické texty v UI podľa aktuálneho jazyka."""
        self.tabs.setTabText(0, self.tr("1. Vstup a Nastavenia"))
        self.tabs.setTabText(1, self.tr("2. Editor Segmentov"))
        self.tabs.setTabText(2, self.tr("3. Finálny Výstup"))

        self.input_group.setTitle(self.tr("Hlavný textový vstup"))
        self.text_input.setPlaceholderText(self.tr("Vložte sem váš text na prevod na reč..."))
        
        self.settings_group.setTitle(self.tr("Predvolené nastavenia generovania"))
        self.gemini_model_combo_label.setText(self.tr("TTS Model:"))
        self.gemini_voice_combo_label.setText(self.tr("Predvolený Hlas:"))
        self.voice_preview_button.setText(self.tr("🔊 Ukážka"))
        self.language_combo_label.setText(self.tr("Jazyk:"))
        self.style_combo_label.setText(self.tr("Štýl (predvoľba):"))
        self.prompt_label.setText(self.tr("Prompt (EN):"))
        self.style_prompt_input.setPlaceholderText(self.tr("Vlastný 'Style Prompt' v angličtine..."))
        
        self.speed_label.setText(self.tr("Rýchlosť Reči:") + f" {self.speed_slider.value()/100:.2f}x")
        self.temp_label.setText(self.tr("Teplota:") + f" {self.temp_slider.value()/10:.1f}")
        
        self.control_group.setTitle(self.tr("Ovládanie segmentácie a generovania"))
        self.use_full_text_checkbox.setText(self.tr("Použiť celý text ako jeden segment"))
        self.segment_count_label.setText(self.tr("Viet/Segment:") + f" {self.segment_count_slider.value()}")
        self.split_button.setText(self.tr("✂ Rozdeliť text na segmenty"))
        self.generate_all_button.setText(self.tr("🚀 Generovať VŠETKY Segmenty"))
        
        self.segments_group.setTitle(self.tr("Segmenty"))
        self.add_segment_button.setText(self.tr("➕ Vložiť Prázdny Segment"))
        
        self.full_gen_group.setTitle(self.tr("Finálny výstup"))
        if self.full_waveform_label.pixmap().isNull():
            self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty pre zobrazenie celkovej waveform."))
        self.merge_segments_button.setText(self.tr("➕ Zlúčiť Segmenty"))
        self.play_full_button.setText(self.tr("▶ Prehrať Celok") if "▶" in self.play_full_button.text() else self.tr("◼ Zastaviť Celok"))
        self.save_full_button.setText(self.tr("💾 Uložiť WAV"))
        self.stop_all_button.setText(self.tr("◼ STOP"))

        # Preklad menu (aktualizácia prebehne automaticky rekonštrukciou textov, ale mení sa len názov QAction)
        self.file_menu.setTitle(self.tr("Súbor"))
        self.new_action.setText(self.tr("Nový Projekt"))
        self.open_action.setText(self.tr("Načítať Projekt..."))
        self.save_action.setText(self.tr("Uložiť Projekt..."))
        self.save_audio_action.setText(self.tr("Uložiť Celý WAV..."))
        self.exit_action.setText(self.tr("Ukončiť"))

        self.tools_menu.setTitle(self.tr("Nástroje"))
        self.clean_temp_action.setText(self.tr("Vyčistiť dočasné súbory"))
        if hasattr(self, 'set_api_key_action'):
            self.set_api_key_action.setText(self.tr("Nastaviť API kľúč..."))
        if hasattr(self, 'set_pricing_action'):
            self.set_pricing_action.setText(self.tr("Nastaviť sadzby (Cenník)..."))
        
        self.help_menu.setTitle(self.tr("Pomoc"))
        self.about_action.setText(self.tr("O programe"))

        # Aktualizácia existujúcich segmentov (dynamický preklad UI prvkov v segmentoch)
        for i in range(len(self.segment_data)):
            try:
                play_btn = self.segments_container.findChild(QPushButton, f"play_button_{i}")
                if play_btn:
                    if "▶" in play_btn.text(): play_btn.setText(self.tr("▶ Prehrať"))
                    else: play_btn.setText(self.tr("◼ Zastaviť"))
                
                gen_btn = self.segments_container.findChild(QPushButton, f"generate_button_{i}")
                if gen_btn: gen_btn.setText(self.tr("🔊 Generovať"))
                
                silence_btn = self.segments_container.findChild(QPushButton, f"silence_button_{i}")
                if silence_btn: silence_btn.setText(self.tr("🔇 Ticho"))
                
                del_btn = self.segments_container.findChild(QPushButton, f"delete_button_{i}")
                if del_btn: del_btn.setText(self.tr("🗑 Zmazať"))
                
                tag_btn = self.segments_container.findChild(QPushButton, f"tag_button_{i}")
                if tag_btn: tag_btn.setText(self.tr("🏷️ Vložiť Tag"))
            except Exception:
                pass
                
        # Status bar update len ak je defaultná
        if "pripravená" in self.status_bar.currentMessage() or "ready" in self.status_bar.currentMessage():
            self.status_bar.showMessage(self.tr("Aplikácia pripravená."))

    
    def populate_gemini_voices(self):
        """Naplní ComboBox pevným zoznamom Gemini hlasov s pohlavím."""
        self.gemini_voice_combo.clear()
        
        # --- VYLEPŠENÉ: Zobrazí meno a pohlavie ---
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
        """Spustí vlákno na asynchrónne načítanie aktuálnych modelov."""
        self.model_fetch_thread = QThread()
        self.model_fetch_worker = ModelFetchWorker()
        self.model_fetch_worker.moveToThread(self.model_fetch_thread)
        self.model_fetch_thread.started.connect(self.model_fetch_worker.run)
        self.model_fetch_worker.finished.connect(self.on_models_fetched)
        self.model_fetch_worker.error.connect(self.on_models_fetch_error)
        
        self.gemini_model_combo.setItemText(0, "Načítavam aktuálne modely z API...")
        self.model_fetch_thread.start()

    def on_models_fetched(self, models_dict):
        global GEMINI_TTS_MODELS
        # Ak chceme zachovať pôvodné modely a pridať nové, zjednotíme slovníky
        GEMINI_TTS_MODELS.update(models_dict)
        
        current_text = self.gemini_model_combo.currentText()
        self.gemini_model_combo.clear()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        self.status_bar.showMessage(self.tr("Aktuálne TTS modely úspešne načítané z Gemini API."))
        
        self.model_fetch_thread.quit()
        self.model_fetch_thread.wait()

    def on_models_fetch_error(self, err_msg):
        self.status_bar.showMessage(self.tr("Nepodarilo sa načítať modely, použijú sa predvolené. ({0})").format(err_msg))
        self.gemini_model_combo.clear()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        self.model_fetch_thread.quit()
        self.model_fetch_thread.wait()

    def set_active_text_widget(self, widget: QTextEdit):
        """Uloží referenciu na textové pole, ktoré práve získalo focus."""
        self.active_text_widget = widget

    def get_segment_play_button(self, index: int) -> QPushButton | None:
        """Nájde tlačidlo na prehrávanie segmentu podľa indexu."""
        # Skontrolujeme, či kontajner ešte existuje
        if self.segments_container:
            return self.segments_container.findChild(QPushButton, f"play_button_{index}")
        return None

    def update_segment_play_button_ui(self, index: int, state):
        """Aktualizuje text tlačidla Prehrať/Zastaviť segmentu."""
        button = self.get_segment_play_button(index)
        if button:
             if state == QMediaPlayer.PlaybackState.PlayingState:
                 button.setText("◼ Zastaviť")
             elif state in [QMediaPlayer.PlaybackState.StoppedState, QMediaPlayer.PlaybackState.PausedState]:
                 button.setText("▶ Prehrať")

    def update_play_button_state(self, state):
        """Aktualizuje text tlačidla Prehrať Celok alebo segmentu."""
        is_playing_local_file = self.player.source().isLocalFile()

        # Ak sa neprehráva lokálny súbor (napr. chyba), resetujeme UI
        if not is_playing_local_file:
            is_playing = state == QMediaPlayer.PlaybackState.PlayingState
            self.stop_all_button.setEnabled(is_playing)
            self.set_ui_enabled(not is_playing)
            return

        source_path = self.player.source().toLocalFile()
        is_preview = VOICES_DIR in os.path.normpath(source_path)

        # Ak je zdroj ukážka, neupravuj UI segmentov/celku, iba STOP tlačidlo
        if is_preview:
            is_playing = state == QMediaPlayer.PlaybackState.PlayingState
            self.stop_all_button.setEnabled(is_playing)
            return

        # Reset všetkých segmentových tlačidiel na "Prehrať"
        for i in range(len(self.segment_data)):
            segment_path = self.segment_data[i].get("audio_temp_path")
            # Ak sa neprehráva práve tento segment, resetuj ho
            if segment_path and segment_path != source_path:
                self.update_segment_play_button_ui(i, QMediaPlayer.PlaybackState.StoppedState)

        # Aktualizácia stavu hlavného prehrávača
        if source_path and source_path == self.full_audio_temp_path:
            if state == QMediaPlayer.PlaybackState.PlayingState:
                self.play_full_button.setText("◼ Zastaviť Celok")
            else:
                self.play_full_button.setText("▶ Prehrať Celok")
        else:
            self.play_full_button.setText("▶ Prehrať Celok")

        # Aktualizácia stavu prehrávaného segmentu
        if source_path:
            for i, data in enumerate(self.segment_data):
                if data.get("audio_temp_path") == source_path:
                    self.update_segment_play_button_ui(i, state)
                    break

        # Globálna logika pre UI enable/disable a STOP tlačidlo
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.stop_all_button.setEnabled(is_playing)

        # UŽ NEZAKAZUJEME CELÉ UI POČAS PREHRÁVANIA SEGMENTU (aby bežal multitasking)
        if not (self.batch_thread and self.batch_thread.isRunning()):
            if not is_playing:
                self.set_ui_enabled(True)


    def set_dark_style(self):
        """Nastaví globálny CSS pre tmavý režim a lepšiu estetiku."""
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

        # --- HLAVNÝ TAB WIDGET ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- KARTA 1: Vstup a Nastavenia ---
        self.tab1 = QWidget()
        self.tabs.addTab(self.tab1, "1. Vstup a Nastavenia")
        tab1_layout = QHBoxLayout(self.tab1)

        # ĽAVÝ PANEL: Textový vstup
        left_panel_tab1 = QWidget()
        left_layout_tab1 = QVBoxLayout(left_panel_tab1)
        self.input_group = QGroupBox("Hlavný textový vstup")
        input_layout = QVBoxLayout(self.input_group)
        self.text_input = CustomTextEdit()
        self.text_input.focus_in_signal.connect(self.set_active_text_widget)
        self.text_input.setPlaceholderText("Vložte sem váš text na prevod na reč...")
        input_layout.addWidget(self.text_input)
        left_layout_tab1.addWidget(self.input_group)
        tab1_layout.addWidget(left_panel_tab1, 2) # Väčší pomer

        # PRAVÝ PANEL: Nastavenia a ovládanie
        right_panel_tab1 = QWidget()
        right_layout_tab1 = QVBoxLayout(right_panel_tab1)
        right_layout_tab1.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.settings_group = QGroupBox("Predvolené nastavenia generovania")
        settings_layout = QGridLayout(self.settings_group)

        self.gemini_model_combo_label = QLabel("TTS Model:")
        settings_layout.addWidget(self.gemini_model_combo_label, 0, 0)
        self.gemini_model_combo = QComboBox()
        self.gemini_model_combo.addItems(GEMINI_TTS_MODELS.keys())
        settings_layout.addWidget(self.gemini_model_combo, 0, 1, 1, 2)

        self.gemini_voice_combo_label = QLabel("Predvolený Hlas:")
        settings_layout.addWidget(self.gemini_voice_combo_label, 1, 0)
        self.gemini_voice_combo = QComboBox()
        self.voice_preview_button = QPushButton("🔊 Ukážka")
        self.voice_preview_button.clicked.connect(self.play_voice_preview)
        settings_layout.addWidget(self.gemini_voice_combo, 1, 1)
        settings_layout.addWidget(self.voice_preview_button, 1, 2)
        
        # NOVÉ: Výber jazyka
        self.language_combo_label = QLabel("Jazyk:")
        settings_layout.addWidget(self.language_combo_label, 2, 0)
        self.language_combo = QComboBox()
        self.language_combo.addItems(SUPPORTED_LANGUAGES.keys())
        self.language_combo.setCurrentText("Slovak (SK)") # Predvolený jazyk
        settings_layout.addWidget(self.language_combo, 2, 1, 1, 2)

        self.style_combo_label = QLabel("Štýl (predvoľba):")
        settings_layout.addWidget(self.style_combo_label, 3, 0)
        self.style_prompt_combo = QComboBox()
        self.style_prompt_combo.addItems(STYLE_PROMPT_OPTIONS.keys())
        self.style_prompt_combo.currentIndexChanged.connect(self.update_style_prompt_text)
        settings_layout.addWidget(self.style_prompt_combo, 3, 1, 1, 2)

        self.prompt_label = QLabel("Prompt (EN):")
        settings_layout.addWidget(self.prompt_label, 4, 0, Qt.AlignmentFlag.AlignTop)
        self.style_prompt_input = QTextEdit()
        self.style_prompt_input.setPlaceholderText("Vlastný 'Style Prompt' v angličtine...")
        self.style_prompt_input.setMaximumHeight(60)
        settings_layout.addWidget(self.style_prompt_input, 4, 1, 1, 2)
        
        # NOVÉ: Slider pre rýchlosť reči
        self.speed_label = QLabel("Rýchlosť Reči: 1.00x")
        settings_layout.addWidget(self.speed_label, 5, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400) # Rozsah 0.25x až 4.00x
        self.speed_slider.setValue(100) # Predvolená rýchlosť 1.00x
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText(self.tr("Rýchlosť Reči:") + f" {v/100:.2f}x"))
        settings_layout.addWidget(self.speed_slider, 5, 1, 1, 2)

        self.temp_label = QLabel(f"Teplota: 1.0")
        settings_layout.addWidget(self.temp_label, 6, 0)
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 20)
        self.temp_slider.setValue(10)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_label.setText(self.tr("Teplota:") + f" {v/10:.1f}"))
        settings_layout.addWidget(self.temp_slider, 6, 1, 1, 2)
        
        right_layout_tab1.addWidget(self.settings_group)

        self.control_group = QGroupBox("Ovládanie segmentácie a generovania")
        control_layout = QVBoxLayout(self.control_group)
        
        self.use_full_text_checkbox = QCheckBox("Použiť celý text ako jeden segment")
        self.use_full_text_checkbox.stateChanged.connect(self.toggle_segmentation_controls)
        control_layout.addWidget(self.use_full_text_checkbox)

        segment_count_layout = QHBoxLayout()
        self.segment_count_slider = QSlider(Qt.Orientation.Horizontal)
        self.segment_count_slider.setRange(1, 10)
        self.segment_count_slider.setValue(3)
        self.segment_count_label = QLabel(f"Viet/Segment: {self.segment_count_slider.value()}")
        segment_count_layout.addWidget(self.segment_count_label)
        segment_count_layout.addWidget(self.segment_count_slider)
        control_layout.addLayout(segment_count_layout)

        self.split_button = QPushButton("✂ Rozdeliť text na segmenty")
        self.split_button.clicked.connect(self.split_text_and_display)
        control_layout.addWidget(self.split_button)

        self.segment_count_slider.valueChanged.connect(self.update_split_button_on_slider_change)
        self.update_split_button_on_slider_change(self.segment_count_slider.value())

        self.generate_all_button = QPushButton("🚀 Generovať VŠETKY Segmenty")
        self.generate_all_button.clicked.connect(self.start_batch_generation)
        self.generate_all_button.setEnabled(False)
        control_layout.addWidget(self.generate_all_button)

        right_layout_tab1.addWidget(self.control_group)
        right_layout_tab1.addStretch()
        tab1_layout.addWidget(right_panel_tab1, 1)

        # --- KARTA 2: Segmenty ---
        self.tab2 = QWidget()
        self.tabs.addTab(self.tab2, "2. Editor Segmentov")
        tab2_layout = QVBoxLayout(self.tab2)
        self.segments_group = QGroupBox("Segmenty")
        segments_main_layout = QVBoxLayout(self.segments_group)

        self.add_segment_button = QPushButton("➕ Vložiť Prázdny Segment")
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

        # --- KARTA 3: Finálny výstup ---
        self.tab3 = QWidget()
        self.tabs.addTab(self.tab3, "3. Finálny Výstup")
        tab3_layout = QVBoxLayout(self.tab3)
        tab3_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.full_gen_group = QGroupBox("Finálny výstup")
        self.full_gen_group.setMaximumWidth(1000)
        self.full_gen_layout = QHBoxLayout(self.full_gen_group)

        self.full_waveform_label = QLabel()
        self.full_waveform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.full_waveform_label.setMinimumHeight(80)
        self.full_waveform_label.setMinimumWidth(300)
        self.full_gen_layout.addWidget(self.full_waveform_label, 2)

        full_button_layout = QVBoxLayout()
        self.merge_segments_button = QPushButton("➕ Zlúčiť Segmenty")
        self.merge_segments_button.clicked.connect(self.merge_segments_audio)
        self.merge_segments_button.setEnabled(False)
        full_button_layout.addWidget(self.merge_segments_button)

        play_save_layout = QHBoxLayout()
        self.play_full_button = QPushButton("▶ Prehrať Celok")
        self.play_full_button.setEnabled(False)
        self.play_full_button.clicked.connect(self.play_full_audio)
        play_save_layout.addWidget(self.play_full_button)

        self.save_full_button = QPushButton("💾 Uložiť WAV")
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
        self.cost_label = QLabel("Cena: $0.000000")
        self.status_bar.addPermanentWidget(self.pro_char_label)
        self.status_bar.addPermanentWidget(self.flash_char_label)
        self.status_bar.addPermanentWidget(self.tokens_label)
        self.status_bar.addPermanentWidget(self.cost_label)
        
        self.status_bar.showMessage("Aplikácia pripravená.")

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
        selected_sk_name = self.style_prompt_combo.currentText()
        selected_en_prompt = STYLE_PROMPT_OPTIONS.get(selected_sk_name, "")
        self.style_prompt_input.setText(selected_en_prompt)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("Súbor")
        
        self.new_action = QAction("Nový Projekt", self); self.new_action.setShortcut(QKeySequence.StandardKey.New); self.new_action.triggered.connect(self.new_project); self.file_menu.addAction(self.new_action)
        self.open_action = QAction("Načítať Projekt...", self); self.open_action.setShortcut(QKeySequence.StandardKey.Open); self.open_action.triggered.connect(self.load_project); self.file_menu.addAction(self.open_action)
        self.save_action = QAction("Uložiť Projekt...", self); self.save_action.setShortcut(QKeySequence.StandardKey.Save); self.save_action.triggered.connect(self.save_project); self.file_menu.addAction(self.save_action)
        
        self.file_menu.addSeparator()
        self.save_audio_action = QAction("Uložiť Celý WAV...", self); self.save_audio_action.triggered.connect(self.save_audio); self.file_menu.addAction(self.save_audio_action)
        self.file_menu.addSeparator()
        
        self.exit_action = QAction("Ukončiť", self); self.exit_action.setShortcut(QKeySequence.StandardKey.Quit); self.exit_action.triggered.connect(self.close); self.file_menu.addAction(self.exit_action)
        
        self.tools_menu = menu_bar.addMenu("Nástroje")
        self.clean_temp_action = QAction("Vyčistiť dočasné súbory", self); self.clean_temp_action.triggered.connect(self.temp_file_manager.cleanup); self.tools_menu.addAction(self.clean_temp_action)
        self.set_api_key_action = QAction("Nastaviť API kľúč...", self); self.set_api_key_action.triggered.connect(self.set_api_key_dialog); self.tools_menu.addAction(self.set_api_key_action)
        self.set_pricing_action = QAction("Nastaviť sadzby (Cenník)...", self); self.set_pricing_action.triggered.connect(self.set_pricing_dialog); self.tools_menu.addAction(self.set_pricing_action)
        
        # Jazykové menu bolo odstránené
        
        self.help_menu = menu_bar.addMenu("Pomoc")
        self.about_action = QAction("O programe", self); self.about_action.triggered.connect(lambda: QMessageBox.information(self, self.tr("O programe"), "Gemini TTS Generátor: Ukážka segmentovaného prevodu textu na reč pomocou Google Gemini API.")); self.help_menu.addAction(self.about_action)

    def set_api_key_dialog(self):
        global GEMINI_API_KEY
        key, ok = QInputDialog.getText(self, self.tr("Nastavenie API kľúča"), self.tr("Vložte váš Gemini API kľúč:"), QLineEdit.EchoMode.Password)
        if ok and key:
            GEMINI_API_KEY = key.strip()
            self.save_settings()
            self.status_bar.showMessage(self.tr("API kľúč bol úspešne uložený."))
            self.fetch_dynamic_models() # Skúsiť načítať modely s novým kľúčom
            
    def set_pricing_dialog(self):
        pro_price, ok1 = QInputDialog.getDouble(self, self.tr("Cenník (Pro)"), self.tr("Sadzba za 1 milión tokenov/znakov pre PRO model (v $):"), self.pro_rate, 0, 1000, 6)
        if ok1:
            self.pro_rate = pro_price
            flash_price, ok2 = QInputDialog.getDouble(self, self.tr("Cenník (Flash)"), self.tr("Sadzba za 1 milión tokenov/znakov pre FLASH model (v $):"), self.flash_rate, 0, 1000, 6)
            if ok2:
                self.flash_rate = flash_price
                self.save_settings()
                self.update_char_count_labels()
                self.status_bar.showMessage(self.tr("Sadzby úspešne uložené."))
            
    def insert_markup_tag_into_segment(self, tag: str, text_widget: QTextEdit):
        if text_widget:
            text_widget.setFocus()
            text_widget.textCursor().insertText(tag + " ")
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            text_widget.setTextCursor(cursor)
        else:
             self.show_error_message("Nastala chyba: textové pole segmentu nebolo nájdené.")

    # --- VYLEPŠENÉ: MULTITASKING (bod 3) ---
    def start_generation(self, segment_index: int):
        # --- NOVÉ: Kontrola existencie API kľúča ---
        if not GEMINI_API_KEY:
            self.show_error_message(self.tr("Gemini API kľúč nebol nájdený.\n\nNastavte ho v menu 'Nástroje' -> 'Nastaviť API kľúč...'."))
            return

        # Ak už beží dávkové generovanie, nerob nič
        if self.batch_thread and self.batch_thread.isRunning():
            self.show_error_message(self.tr("Prebieha dávkové generovanie. Zrušte ho, ak chcete generovať iba jeden segment."))
            return

        # Ak pre tento segment už beží generovanie, nerob nič
        # ZMENA: Kontrola pre štandardné Python vlákno
        if segment_index in self.active_single_gen_threads and self.active_single_gen_threads[segment_index].is_alive():
            self.status_bar.showMessage(self.tr("Generuje sa..."))
            return

        text_widget = self.segment_data[segment_index].get("text_widget")
        if not text_widget:
            self.show_error_message(self.tr("Segment neobsahuje UI prvok textu."))
            return

        text_to_generate = text_widget.toPlainText().strip()
        if not text_to_generate:
            self.show_error_message(self.tr("Segment neobsahuje text na generovanie."))
            return

        self.set_segment_ui_enabled(segment_index, False)
        self.segment_data[segment_index]["text"] = text_to_generate

        selected_model_display_name = self.gemini_model_combo.currentText()
        selected_model = GEMINI_TTS_MODELS.get(selected_model_display_name, list(GEMINI_TTS_MODELS.values())[0])
        style_prompt = self.style_prompt_input.toPlainText().strip()
        
        language_display_name = self.language_combo.currentText()
        language_code = SUPPORTED_LANGUAGES.get(language_display_name, "sk-SK")
        speaking_rate = self.speed_slider.value() / 100.0

        # --- VYLEPŠENÉ: Načítanie hlasu pre konkrétny segment ---
        segment_voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{segment_index}")
        selected_voice = segment_voice_combo.currentData() if segment_voice_combo else self.gemini_voice_combo.currentData()

        waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{segment_index}")
        if waveform_label:
            waveform_label.setText(f"Generuje sa...")
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

        # --- NOVÁ LOGIKA S POUŽITÍM threading.Thread ---
        
        # 1. Vytvoríme objekt so signálmi
        signals = WorkerSignals()
        
        # 2. Prepojíme signály s našimi metódami v hlavnom okne
        signals.finished.connect(lambda result, idx=segment_index: self.on_generation_finished(result, idx))
        signals.error.connect(lambda error_msg, idx=segment_index: self.on_generation_error(error_msg, idx))
        
        # 3. Vytvoríme inštanciu workera (už to nie je QObject)
        worker = GeminiWorker(params, signals)
        
        # 4. Vytvoríme a spustíme štandardné Python vlákno
        thread = Thread(target=worker.run, daemon=True)
        # Uložíme referenciu na vlákno pre kontrolu stavu (is_alive)
        self.active_single_gen_threads[segment_index] = thread

        self.status_bar.showMessage(self.tr("Generujem reč (Segment {0})...").format(segment_index + 1))
        thread.start()

    def on_generation_finished(self, result, segment_index):
        audio_content = result["audio_content"]
        char_count = result["char_count"]
        model_used = result["model_used"]
        in_tok = result.get("in_tokens", 0)
        out_tok = result.get("out_tokens", 0)

        # ZMENA: Odstránime vlákno po dokončení
        self.active_single_gen_threads.pop(segment_index, None)

        self.in_tokens_count += in_tok
        self.out_tokens_count += out_tok

        units = in_tok + out_tok if (in_tok + out_tok) > 0 else char_count

        # Aktualizácia počítadla znakov a ceny
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
        self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty..."))
        self.full_waveform_label.setPixmap(QPixmap())

        can_merge = all(s.get("audio") is not None for s in self.segment_data)
        self.merge_segments_button.setEnabled(can_merge)

        self.status_bar.showMessage(self.tr("Segment {0} vygenerovaný.").format(segment_index + 1))

    def on_generation_error(self, error_message, segment_index):
        self.active_single_gen_threads.pop(segment_index, None)

        waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{segment_index}")
        if waveform_label:
            waveform_label.setText(self.tr("Generovanie ZLYHALO."))
            waveform_label.setPixmap(QPixmap())

        self.set_segment_ui_enabled(segment_index, True)
        self.show_error_message(self.tr("Chyba pri generovaní segmentu {0}:\n{1}").format(segment_index + 1, error_message))
        self.status_bar.showMessage(self.tr("Počas generovania segmentu {0} nastala chyba.").format(segment_index + 1))

    def cleanup_worker_and_thread(self):
         pass

    def start_batch_generation(self):
        if not GEMINI_API_KEY:
            self.show_error_message(self.tr("Gemini API kľúč nebol nájdený.\n\nNastavte ho v menu 'Nástroje' -> 'Nastaviť API kľúč...'."))
            return

        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()
            return

        active_single_threads = {k: v for k, v in self.active_single_gen_threads.items() if v.is_alive()}
        if active_single_threads:
             self.show_error_message(self.tr("Prebieha generovanie jednotlivých segmentov. Dávkové generovanie nie je možné spustiť."))
             return

        # Ak je zaškrtnuté použitie celého textu, automaticky aktualizujeme segment pred generovaním
        if self.use_full_text_checkbox.isChecked():
            main_text = self.text_input.toPlainText().strip()
            if not main_text:
                self.show_error_message(self.tr("Zadajte prosím text na spracovanie."))
                return
            
            needs_split = True
            if len(self.segment_data) == 1:
                # Skontroluj text_widget aj čistý text
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
            self.show_error_message(self.tr("Všetky segmenty už majú vygenerované audio alebo sú prázdne."))
            return

        self.stop_all_audio()

        prompt = self.style_prompt_input.toPlainText().strip()
        temperature = self.temp_slider.value() / 10.0
        model = GEMINI_TTS_MODELS.get(self.gemini_model_combo.currentText())
        
        language_display_name = self.language_combo.currentText()
        language_code = SUPPORTED_LANGUAGES.get(language_display_name, "sk-SK")
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
        self.generate_all_button.setText(self.tr("◼ Zrušiť Generovanie"))
        try: self.generate_all_button.clicked.disconnect()
        except TypeError: pass
        self.generate_all_button.clicked.connect(self.cancel_batch_generation)

        for s_info in segments_to_process:
            idx = s_info["original_index"]
            waveform_label = self.segments_container.findChild(QLabel, f"waveform_label_{idx}")
            if waveform_label:
                waveform_label.setText(self.tr("Čaká sa..."))
                waveform_label.setPixmap(QPixmap())

        self.status_bar.showMessage(self.tr("Spúšťam dávkové generovanie {0} segmentov...").format(len(segments_to_process)))
        self.tabs.setCurrentIndex(1)
        self.batch_thread.start()

    def cancel_batch_generation(self):
        if self.batch_thread and self.batch_thread.isRunning() and self.batch_worker:
            self.batch_worker.cancel()
            self.status_bar.showMessage(self.tr("Ruším generovanie..."))
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
            self.status_bar.showMessage(self.tr("Dávkové generovanie dokončené! Audio automaticky zlúčené."))
            self.tabs.setCurrentIndex(2) # Prepni na finálny výstup
        else:
            self.status_bar.showMessage(self.tr("Dávkové generovanie zrušené."))
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
        self.show_error_message(self.tr("Chyba dávkového generovania: {0}").format(message))
        self.status_bar.showMessage(self.tr("Chyba: Dávkové generovanie zlyhalo."))

    def new_project(self):
        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()
        
        # ZMENA: Ukončenie všetkých bežiacich single-threads
        for index, thread in list(self.active_single_gen_threads.items()):
            if thread.is_alive():
                 print(f"INFO: Ukončujem bežiaci single-thread pre segment {index+1} (daemon vlákno by malo skončiť po dokončení).")
            # Odstránime záznam, hoci vlákno ešte môže chvíľu bežať
            del self.active_single_gen_threads[index]

        self.audio_content = None
        self.full_audio_temp_path = None
        self.segment_data = []
        self.active_text_widget = None
        self.text_input.clear()
        self.style_prompt_input.clear()
        self.style_prompt_combo.setCurrentIndex(0)
        
        # --- VYLEPŠENÉ: Reset počítadiel ---
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

        self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty..."))
        self.full_waveform_label.setPixmap(QPixmap())
        self.status_bar.showMessage(self.tr("Vytvorený nový projekt."))
        self.tabs.setCurrentIndex(0)

    def save_project(self):
        # --- ZMENA: Dialóg sa otvára v adresári /project ---
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("Uložiť Projekt..."), PROJECTS_DIR, "Gemini TTS Project (*.gtts)")

        if file_path:
            try:
                settings = {
                    "model_display_name": self.gemini_model_combo.currentText(),
                    "voice": self.gemini_voice_combo.currentData(),
                    "prompt": self.style_prompt_input.toPlainText().strip(),
                    "temperature": self.temp_slider.value(),
                    "segment_count": self.segment_count_slider.value(),
                    "full_text": self.text_input.toPlainText().strip(),
                    "language": self.language_combo.currentText(),
                    "speed": self.speed_slider.value(),
                    # --- VYLEPŠENÉ: Uloženie počítadiel ---
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
                    
                    # --- VYLEPŠENÉ: Získanie hlasu zo segmentu ---
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
                self.status_bar.showMessage(self.tr("Projekt úspešne uložený do: {0}").format(file_path))
            except Exception as e:
                self.show_error_message(self.tr("Chyba pri ukladaní projektu: {0}").format(e))

    def load_project(self):
        # --- ZMENA: Dialóg sa otvára v adresári /project ---
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("Načítať Projekt"), PROJECTS_DIR, "Gemini TTS Project (*.gtts)")

        if file_path:
            try:
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
                    sk_key = [k for k, v in STYLE_PROMPT_OPTIONS.items() if v == current_prompt]
                    if sk_key: self.style_prompt_combo.setCurrentText(sk_key[0])

                self.temp_slider.setValue(settings.get("temperature", 10))
                self.segment_count_slider.setValue(settings.get("segment_count", 3))
                self.text_input.setText(settings.get("full_text", ""))

                if settings.get("language") in SUPPORTED_LANGUAGES:
                    self.language_combo.setCurrentText(settings["language"])
                self.speed_slider.setValue(settings.get("speed", 100))
                
                # --- VYLEPŠENÉ: Načítanie počítadiel ---
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
                        
                        # --- VYLEPŠENÉ: Načítanie hlasu pre segment ---
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
                    self.status_bar.showMessage(self.tr("Projekt načítaný s {0} segmentmi.").format(len(self.segment_data)))
                else:
                    self.status_bar.showMessage(self.tr("Projekt načítaný. Rozdeľte text na segmenty."))
            except Exception as e:
                self.show_error_message(self.tr("Chyba pri načítaní projektu: {0}").format(e))
                self.new_project()
    
    # --- UPRAVENÁ FUNKCIA ---
    def split_text_and_display(self):
        text = self.text_input.toPlainText().strip()
        if not text:
            self.show_error_message(self.tr("Zadajte prosím text na spracovanie."))
            return

        if self.batch_thread and self.batch_thread.isRunning():
            self.cancel_batch_generation()

        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()

        sentences = []
        # --- ZMENA: Rozhodovanie podľa checkboxu ---
        if self.use_full_text_checkbox.isChecked():
            sentences.append(text)
        else:
            sentences_per_segment = self.segment_count_slider.value()
            sentences = _split_text_into_segments(text, sentences_per_segment)

        if not sentences:
            self.show_error_message(self.tr("Text nebolo možné spracovať na segmenty."))
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

        self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty..."))
        self.full_waveform_label.setPixmap(QPixmap())
        
        if self.use_full_text_checkbox.isChecked():
            self.status_bar.showMessage(self.tr("Vytvorený 1 segment z celého textu."))
        else:
            self.status_bar.showMessage(self.tr("Text rozdelený na {0} segmentov.").format(len(self.segment_data)))
        
        self.tabs.setCurrentIndex(1) # Automaticky prepni na kartu so segmentmi


    def delete_segment(self, index: int):
        if 0 <= index < len(self.segment_data):
            if self.player.source().isLocalFile() and self.player.source().toLocalFile() == self.segment_data[index].get("audio_temp_path"):
                self.player.stop()
            
            # ZMENA: Zastavenie single-thread
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                # Demon vlákno skončí samo, len odstránime referenciu, aby UI nečakalo
                 del self.active_single_gen_threads[index] 
                 
            del self.segment_data[index]
            if not self.segment_data:
                self.generate_all_button.setEnabled(False)
                self.merge_segments_button.setEnabled(False)
            self.audio_content = None
            self.full_audio_temp_path = None
            self.play_full_button.setEnabled(False)
            self.save_full_button.setEnabled(False)
            self.full_waveform_label.setText(self.tr("Krivka: Zlúčte segmenty..."))
            self.full_waveform_label.setPixmap(QPixmap())
            self.display_segments()
            can_merge = all(s.get("audio") for s in self.segment_data)
            self.merge_segments_button.setEnabled(can_merge and len(self.segment_data) > 0)
            self.status_bar.showMessage(self.tr("Segment zmazaný. Ostáva {0} segmentov.").format(len(self.segment_data)))

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

            # --- VYLEPŠENÉ: Vertikálne tlačidlá na posun ---
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
            text_input.setFixedHeight(110) # Fixná výška na približne 5 riadkov
            text_input.setObjectName(f"text_input_segment_{i}")
            self.segment_data[i]["text_widget"] = text_input
            segment_grid.addWidget(text_input, 0, 2, 1, 2)

            waveform_label = QLabel(self.tr("Krivka nevygenerovaná"))
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
            tag_button = QPushButton(self.tr("🏷️ Vložiť Tag"));
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

            # --- VYLEPŠENÉ: Výber hlasu pre segment ---
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


            gen_button = QPushButton(self.tr("🔊 Generovať")); gen_button.clicked.connect(lambda checked, idx=i: self.start_generation(segment_index=idx)); gen_button.setObjectName(f"gen_button_{i}"); control_layout.addWidget(gen_button)
            play_button = QPushButton(self.tr("▶ Prehrať")); play_button.setEnabled(data.get("audio") is not None); play_button.setObjectName(f"play_button_{i}"); play_button.clicked.connect(lambda checked, idx=i: self.play_segment_audio(idx)); control_layout.addWidget(play_button)
            
            # --- VYLEPŠENÉ: Pridané tlačidlo na ticho ---
            silence_button = QPushButton(self.tr("🔇 Ticho")); silence_button.setObjectName(f"silence_button_{i}"); silence_button.clicked.connect(lambda checked, idx=i: self.add_silence_to_segment(idx)); control_layout.addWidget(silence_button)
            
            delete_button = QPushButton(self.tr("🗑 Zmazať")); delete_button.setObjectName(f"delete_button_{i}"); delete_button.clicked.connect(lambda checked, idx=i: self.delete_segment(idx)); control_layout.addWidget(delete_button)

            segment_grid.addLayout(control_layout, 1, 3, Qt.AlignmentFlag.AlignVCenter)
            segment_grid.setColumnStretch(2, 3)
            segment_grid.setColumnStretch(3, 2)

            self.segments_layout.addWidget(segment_widget)
            
    def on_segment_voice_changed(self, index):
        """Uloží zmenu hlasu do dátovej štruktúry segmentu."""
        voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{index}")
        if voice_combo:
            self.segment_data[index]["voice"] = voice_combo.currentData()

    def play_voice_preview(self):
        """Dynamicky vygeneruje a prehrá ukážku vybraného hlasu, alebo prehrá z trvalej cache."""
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
            self.status_bar.showMessage(self.tr("Prehrávanie ukážky zastavené."))
            return

        if os.path.exists(preview_path):
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(preview_path))
            self.player.play()
            self.status_bar.showMessage(self.tr("Prehrávam lokálnu ukážku hlasu: {0}...").format(voice_name))
            return

        # If we need to generate:
        if not GEMINI_API_KEY:
            self.show_error_message(self.tr("Gemini API kľúč nebol nájdený.\n\nNastavte ho v menu 'Nástroje' -> 'Nastaviť API kľúč...'."))
            return

        if self.active_preview_thread and self.active_preview_thread.is_alive():
            self.status_bar.showMessage(self.tr("Generujem..."))
            return

        self.voice_preview_button.setEnabled(False)
        self.voice_preview_button.setText(self.tr("Generujem..."))
        self.status_bar.showMessage(self.tr("Generujem ukážku hlasu: {0}...").format(voice_name))

        # Dynamická tvorba textu podľa jazyka
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
            self.show_error_message(self.tr("Chyba pri ukladaní ukážky: {0}").format(e))
            self.voice_preview_button.setEnabled(True)
            self.voice_preview_button.setText(self.tr("🔊 Ukážka"))
            return
            
        self.voice_preview_button.setEnabled(True)
        self.voice_preview_button.setText(self.tr("🔊 Ukážka"))
        
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(audio_path))
        self.player.play()
        self.status_bar.showMessage(self.tr("Prehrávam lokálnu ukážku hlasu: {0}...").format(voice_name))

    def on_preview_error(self, error_msg):
        self.voice_preview_button.setEnabled(True)
        self.voice_preview_button.setText(self.tr("🔊 Ukážka"))
        self.show_error_message(self.tr("Chyba pri generovaní ukážky hlasu:\n{0}").format(error_msg))
        self.status_bar.showMessage(self.tr("Chyba pri generovaní ukážky hlasu."))

    # ODSTRÁNENÉ: Metódy on_preview_download_finished a on_preview_download_error

    def play_segment_audio(self, index: int):
        """Prehrá alebo zastaví audio vybraného segmentu."""
        audio_path = self.segment_data[index].get("audio_temp_path")
        if not audio_path:
            self.show_error_message(self.tr("Audio pre tento segment nebolo vygenerované."))
            return

        current_source_path = ""
        if self.player.source().isLocalFile():
            current_source_path = self.player.source().toLocalFile()

        # OPRAVA: Použitie os.path.normpath pre spoľahlivé porovnanie ciest
        is_playing_this = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and
            os.path.normpath(current_source_path) == os.path.normpath(audio_path)
        )

        if is_playing_this:
            self.player.stop()
        else:
            self.player.stop() # Najprv zastaví čokoľvek, čo sa prehráva
            self.player.setSource(QUrl.fromLocalFile(audio_path))
            self.player.play()
            self.status_bar.showMessage(self.tr("Prehrávam segment {0}...").format(index + 1))

    def merge_segments_audio(self):
        if not self.segment_data: return
        audio_chunks = [s.get("audio") for s in self.segment_data]
        if any(chunk is None for chunk in audio_chunks):
            self.show_error_message(self.tr("Nie všetky segmenty majú vygenerované audio."))
            return

        self.set_ui_enabled(False)
        try:
            all_frames, sample_rate, nchannels, sampwidth = [], -1, -1, -1
            for i, chunk in enumerate(audio_chunks):
                with wave.open(io.BytesIO(chunk), 'rb') as raw:
                    if sample_rate == -1:
                        sample_rate, nchannels, sampwidth = raw.getframerate(), raw.getnchannels(), raw.getsampwidth()
                    elif (raw.getframerate() != sample_rate or raw.getnchannels() != nchannels or raw.getsampwidth() != sampwidth):
                        raise ValueError(f"Segment {i+1} má nekonzistentné audio parametre.")
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
            self.status_bar.showMessage(self.tr("Segmenty úspešne zlúčené!"))
        except Exception as e:
            self.show_error_message(self.tr("Chyba pri zlúčení audio segmentov: {0}").format(e))
        finally:
            self.set_ui_enabled(True)


    def media_player_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            self.show_error_message(self.tr("Chyba prehrávača: {0}").format(error_string))
            self.status_bar.showMessage(self.tr("Chyba prehrávača."))
            self.set_ui_enabled(True)

    def play_full_audio(self):
        if not self.full_audio_temp_path or not self.audio_content:
            return

        current_source_is_local = self.player.source().isLocalFile()
        current_source_path = self.player.source().toLocalFile() if current_source_is_local else None
        is_playing_full = (current_source_path == self.full_audio_temp_path and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

        if is_playing_full:
            self.player.stop()
        else:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(self.full_audio_temp_path))
            self.player.play()
            self.status_bar.showMessage(self.tr("Prehrávam finálny zvuk..."))

    def stop_all_audio(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.player.stop()
            self.status_bar.showMessage(self.tr("Prehrávanie zastavené."))
        if not (self.batch_thread and self.batch_thread.isRunning()):
            self.set_ui_enabled(True)

    def save_audio(self):
        if not self.audio_content:
            self.show_error_message(self.tr("Žiadny zvuk na uloženie. Najprv zlúčte segmenty."))
            return
        file_path, _ = QFileDialog.getSaveFileName(self, self.tr("Uložiť Audio Súbor"), "gemini_output.wav", "Audio Files (*.wav *.mp3);;WAV Audio Files (*.wav);;MP3 Audio Files (*.mp3)")
        if file_path:
            try:
                if file_path.lower().endswith(".mp3"):
                    if AudioSegment is None:
                        self.show_error_message(self.tr("Pre ukladanie do MP3 je potrebné nainštalovať knižnicu pydub a FFmpeg.\nOtvorte terminál a zadajte: pip install pydub"))
                        return
                    audio = AudioSegment.from_wav(io.BytesIO(self.audio_content))
                    audio.export(file_path, format="mp3", bitrate="192k")
                else:
                    with open(file_path, "wb") as out:
                        out.write(self.audio_content)
                self.status_bar.showMessage(self.tr("Súbor úspešne uložený: {0}").format(file_path))
            except Exception as e:
                self.show_error_message(self.tr("Chyba pri ukladaní súboru: {0}").format(e))

    # --- VYLEPŠENÉ: Granulárne ovládanie UI pre multitasking ---
    def set_segment_ui_enabled(self, index: int, enabled: bool):
        """Zapne/vypne UI prvky pre JEDEN segment."""
        gen_button = self.segments_container.findChild(QPushButton, f"gen_button_{index}")
        silence_button = self.segments_container.findChild(QPushButton, f"silence_button_{index}")
        delete_button = self.segments_container.findChild(QPushButton, f"delete_button_{index}")
        text_widget = self.segment_data[index].get("text_widget")
        voice_combo = self.segments_container.findChild(QComboBox, f"voice_combo_{index}")

        if gen_button:
            gen_button.setEnabled(enabled)
            # ZMENA: Kontrola, či už nebeží generovanie (pre istotu)
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                 gen_button.setText(self.tr("⏳..."))
            else:
                 gen_button.setText(self.tr("🔊 Generovať") if enabled else self.tr("⏳..."))
                 
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
        self.split_button.setEnabled(enabled)
        self.add_segment_button.setEnabled(enabled)

        self.generate_all_button.setEnabled(enabled and len(self.segment_data) > 0)
        if enabled:
            self.generate_all_button.setText(self.tr("Generovať VŠETKY Segmenty"))
            try: self.generate_all_button.clicked.disconnect()
            except: pass
            self.generate_all_button.clicked.connect(self.start_batch_generation)

        is_merged = self.audio_content is not None
        can_merge = bool(self.segment_data) and all(s.get("audio") for s in self.segment_data)
        self.merge_segments_button.setEnabled(enabled and can_merge and not is_merged)
        self.play_full_button.setEnabled(enabled and is_merged)
        self.save_full_button.setEnabled(enabled and is_merged)

        for i, data in enumerate(self.segment_data):
            # ZMENA: Kontrola, či beží single-thread
            is_single_generating = i in self.active_single_gen_threads and self.active_single_gen_threads[i].is_alive()
            
            # Ak beží generovanie pre tento segment, necháme ho vypnutý
            if is_single_generating:
                self.set_segment_ui_enabled(i, False)
                continue
            
            self.set_segment_ui_enabled(i, enabled)
            play_button = self.get_segment_play_button(i)
            if play_button: play_button.setEnabled(enabled and data.get("audio") is not None)
            
            # Tlačidlá na posun
            up_button = self.segments_container.findChild(QPushButton, f"up_button_{i}")
            down_button = self.segments_container.findChild(QPushButton, f"down_button_{i}")
            if up_button: up_button.setEnabled(enabled and i > 0)
            if down_button: down_button.setEnabled(enabled and i < len(self.segment_data) - 1)


        if batch_in_progress:
            self.set_ui_enabled(False)
            self.generate_all_button.setEnabled(True) # Tlačidlo na zrušenie musí ostať aktívne
            self.stop_all_button.setEnabled(True)

    def closeEvent(self, event):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
             self.player.stop()
        if self.batch_thread and self.batch_thread.isRunning():
             self.batch_worker.cancel()
             self.batch_thread.quit()
             self.batch_thread.wait()
        # ZMENA: Daemon vlákna sa ukončia samé pri ukončení hlavného procesu
        # for thread in self.active_single_gen_threads.values():
        #     if thread.is_alive():
        #         # Ak by sme chceli robustné zrušenie, museli by sme pridať cancel mechanizmus
        #         pass 
        self.temp_file_manager.cleanup()
        event.accept()

    def show_error_message(self, message):
        msg_box = QMessageBox(self)
        msg_box.setStyleSheet("background-color: #3c3c3c; color: #f0f0f0;")
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setText(str(message))
        msg_box.setWindowTitle("Chyba")
        msg_box.exec()
        
    # --- NOVÉ FUNKCIE ---

    def toggle_segmentation_controls(self):
        """Prepína stav ovládacích prvkov segmentácie na základe checkboxu."""
        is_checked = self.use_full_text_checkbox.isChecked()
        self.segment_count_slider.setEnabled(not is_checked)
        self.segment_count_label.setEnabled(not is_checked)
        if is_checked:
            self.split_button.setText("📝 Vytvoriť jeden segment")
            self.split_button.setToolTip("Vytvorí jeden segment z celého hlavného textu.")
            self.generate_all_button.setEnabled(True)
        else:
            self.split_button.setText("✂ Rozdeliť text na segmenty")
            # Aktualizuje tooltip podľa aktuálnej hodnoty slidera
            self.update_split_button_on_slider_change(self.segment_count_slider.value())
            self.generate_all_button.setEnabled(len(self.segment_data) > 0)
            
    def update_split_button_on_slider_change(self, value):
        """Aktualizuje label a tooltip pri zmene hodnoty slidera."""
        self.segment_count_label.setText(f"Viet/Segment: {value}")
        # Tooltip sa mení, len ak nie je zaškrtnutá možnosť jedného segmentu
        if not self.use_full_text_checkbox.isChecked():
             self.split_button.setToolTip(f"Rozdelí hlavný text na segmenty po {value} vety.")

    def update_char_count_labels(self):
        """Aktualizuje zobrazenie počtu znakov v stavovom riadku."""
        self.pro_char_label.setText(f"Pro Chars: {self.pro_char_count}")
        self.flash_char_label.setText(f"Flash Chars: {self.flash_char_count}")
        self.tokens_label.setText(f"In/Out Tokens: {self.in_tokens_count}/{self.out_tokens_count}")
        self.cost_label.setText(f"Cena: ${self.total_cost:.6f}")

    def generate_silence_wav(self, duration_s: int, sample_rate: int = 24000, bits_per_sample: int = 16) -> bytes:
        """Generuje WAV dáta pre ticho zadanej dĺžky."""
        num_channels = 1
        bytes_per_sample = bits_per_sample // 8
        num_frames = int(duration_s * sample_rate)
        
        # Tiché dáta (nulové bajty)
        audio_data = b'\x00' * (num_frames * num_channels * bytes_per_sample)
        
        output_buffer = io.BytesIO()
        with wave.open(output_buffer, 'wb') as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(bytes_per_sample)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_data)
        
        return output_buffer.getvalue()

    def add_silence_to_segment(self, index: int):
        """Zobrazí dialóg a pridá ticho do segmentu."""
        duration, ok = QInputDialog.getInt(self, "Vložiť Ticho", "Zadajte dĺžku ticha v sekundách:", 1, 1, 10, 1)
        if ok:
            # Zastav prehrávanie, ak sa prehráva práve tento segment
            if self.player.source().isLocalFile() and self.player.source().toLocalFile() == self.segment_data[index].get("audio_temp_path"):
                self.player.stop()
            
            # ZMENA: Ak beží generovanie, zastav ho (len odstránime referenciu)
            if index in self.active_single_gen_threads and self.active_single_gen_threads[index].is_alive():
                 del self.active_single_gen_threads[index] 
                 self.set_segment_ui_enabled(index, True) # Reset UI

            # Vygeneruj ticho
            audio_content = self.generate_silence_wav(duration)
            self.segment_data[index]["audio"] = audio_content
            audio_path = self.temp_file_manager.create_temp_file(".wav", audio_content)
            self.segment_data[index]["audio_temp_path"] = audio_path
            
            # Vytvor "waveform" pre ticho (plochá čiara)
            png_data = create_waveform_png_data(b'', width=800, height=70) # Prázdne dáta vygenerujú čiaru
            png_path = self.temp_file_manager.create_temp_file(".png", png_data)
            self.segment_data[index]["png_temp_path"] = png_path
            
            # Aktualizuj UI
            self.update_segment_waveform(index, png_path)
            play_button = self.get_segment_play_button(index)
            play_button.setEnabled(True)
            self.update_segment_play_button_ui(index, QMediaPlayer.PlaybackState.StoppedState)

            can_merge = all(s.get("audio") for s in self.segment_data)
            self.merge_segments_button.setEnabled(can_merge)
            
            self.status_bar.showMessage(f"Do segmentu {index + 1} vložené {duration}s ticho.")


    def add_new_segment(self):
        """Vloží nový prázdny segment do zoznamu."""
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
        self.status_bar.showMessage(f"Pridaný nový segment. Celkovo: {len(self.segment_data)}.")


    def move_segment_up(self, index: int):
        """Posunie segment o jednu pozíciu hore."""
        if index > 0:
            self.segment_data.insert(index - 1, self.segment_data.pop(index))
            self.display_segments()


    def move_segment_down(self, index: int):
        """Posunie segment o jednu pozíciu dole."""
        if index < len(self.segment_data) - 1:
            self.segment_data.insert(index + 1, self.segment_data.pop(index))
            self.display_segments()


if __name__ == "__main__":
    if sys.platform.startswith('win'):
        QApplication.setStyle("Fusion")
    app = QApplication(sys.argv)
    window = TTS_App()
    window.show()
    sys.exit(app.exec())