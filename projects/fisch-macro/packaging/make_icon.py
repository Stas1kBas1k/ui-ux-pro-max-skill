"""Turn the Blender-rendered assets/app_icon.png into a trimmed PNG + multi-size Windows .ico (needs Pillow)."""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[1] / "assets"

im = Image.open(ASSETS / "app_icon.png").convert("RGBA")
im = im.crop(im.getbbox())
side = max(im.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
square.save(ASSETS / "app_icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
square.resize((256, 256), Image.LANCZOS).save(ASSETS / "app_icon.png")
print("icon written")
