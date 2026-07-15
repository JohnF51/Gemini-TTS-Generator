import sys
import os
from cx_Freeze import setup, Executable

# Increase recursion limit just in case
sys.setrecursionlimit(sys.getrecursionlimit() * 5)

# Target directory and icon settings
icon_file = "gemini_tts_icon.ico"

# Build options for cx_Freeze
build_exe_options = {
    "packages": [
        "PyQt6",
        "matplotlib",
        "numpy",
        "stanza",
        "pydub",
        "google.genai",
        "ctypes",
        "base64",
        "wave",
        "struct"
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "sqlite3",
        "test",
        "pdb",
        "distutils",
        "stanza.utils"
    ],
    # No local directories like project/, temp/, or voices/ are included
    # start.bat, auto_push.bat, settings.json are excluded by not adding them here
    "include_files": []
}

# Shortcut table for MSI Installer
shortcut_table = [
    (
        "DesktopShortcut",          # Shortcut identifier
        "DesktopFolder",            # Directory_ (System Folder Property)
        "Gemini TTS Generator",     # Name of the shortcut
        "TARGETDIR",                # Component_
        "[TARGETDIR]GeminiTTS.exe", # Target file
        None,                       # Arguments
        "Gemini Text to Speech Generator", # Description
        None,                       # Hotkey
        None,                       # Icon (None = use executable's icon)
        None,                       # IconIndex
        "1",                        # ShowCmd (1 = normal)
        "TARGETDIR"                 # WkDir
    ),
    (
        "StartMenuShortcut",        # Shortcut identifier
        "ProgramMenuFolder",        # Directory_ (System Folder Property)
        "Gemini TTS Generator",     # Name
        "TARGETDIR",
        "[TARGETDIR]GeminiTTS.exe",
        None,
        "Gemini Text to Speech Generator",
        None,
        None,
        None,
        "1",
        "TARGETDIR"
    )
]

msi_data = {
    "Shortcut": shortcut_table
}

# Options for the MSI builder
bdist_msi_options = {
    "upgrade_code": "{3b7b2520-2586-4cfb-b8f1-e1cf59f518e3}",
    "initial_target_dir": r"[ProgramFilesFolder]\Gemini TTS Generator",
    "install_icon": icon_file,
    "data": msi_data
}

# Define base (GUI vs Console)
base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="Gemini TTS Generator",
    version="1.0.0",
    description="Gemini Text to Speech Generator Application",
    author="JohnF51",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options
    },
    executables=[
        Executable(
            "Gemini_TTS.py",
            base=base,
            target_name="GeminiTTS.exe",
            icon=icon_file
        )
    ]
)
