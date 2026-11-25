"""Create the Nora Studio ICO used by the app and setup wizard."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent.parent
target = root / "assets" / "NoraStudio.ico"
target.parent.mkdir(parents=True, exist_ok=True)
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((7, 7, 249, 249), radius=62, fill="#7569DB")
d.rounded_rectangle((20, 20, 236, 236), radius=50, outline="#B7AEFF", width=7)
try:
    font = ImageFont.truetype("arialbd.ttf", 152)
except OSError:
    font = ImageFont.load_default()
d.text((128, 128), "N", font=font, anchor="mm", fill="#FFFFFF")
img.save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(target)
