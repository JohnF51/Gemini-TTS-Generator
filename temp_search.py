import sys

file_path = "j:\\Vlastne_aplikacie\\Gemini_TTS\\Gemini_TTS_v7.py"

queries = ["decrypt_api_key", "gemini.txt", "Nastaviť API kľúč", "self.player.stop", "load_api_key", "settings.json", "Nástroje", "Nastaviť API kľúč..."]

try:
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for i, line in enumerate(lines):
            for q in queries:
                if q in line:
                    print(f"Line {i+1}: {q} -> {line.strip()}")
except Exception as e:
    print("Error:", e)
