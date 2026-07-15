import os
from PIL import Image

def convert_png_to_ico():
    png_path = r"C:\Users\Admin\.gemini\antigravity-ide\brain\f4d3538f-b84c-4ff9-b631-a048378e8e4d\gemini_tts_icon_1784005771895.png"
    ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_tts_icon.ico")
    
    if not os.path.exists(png_path):
        print(f"Error: Source PNG file not found at {png_path}")
        return False
        
    try:
        print(f"Opening PNG: {png_path}")
        img = Image.open(png_path)
        
        # Define icon sizes for standard Windows applications
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        print(f"Saving as multi-resolution ICO to: {ico_path}")
        img.save(ico_path, format="ICO", sizes=sizes)
        print("Icon conversion successful!")
        return True
    except Exception as e:
        print(f"Failed to convert icon: {e}")
        return False

if __name__ == "__main__":
    convert_png_to_ico()
