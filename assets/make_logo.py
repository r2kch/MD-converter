"""Generate the MDConverter app logo in the Netcloud (netcloud.ch) CI style.

Netcloud identity (studied from the live site CSS + favicon):
  * flat rounded-square ("squircle") tile
  * vivid brand blue  (--primary #4640ff, logo-blue #454b9a)
  * one bold, geometric, white glyph, reads clearly at 16px

This draws a bold white Markdown "M↓" mark on a Netcloud-blue squircle with a
subtle vertical gradient + soft top sheen. Everything is drawn at 4x
supersampling then LANCZOS-downscaled so edges are smooth.

Usage (needs Pillow):
  python3 assets/make_logo.py assets
  iconutil -c icns assets/AppIcon.iconset -o assets/AppIcon.icns

Outputs (repo ``assets/`` dir, passed as argv[1]):
  logo-1024.png        master logo
  AppIcon.iconset/     all .icns sizes (iconutil input, gitignored)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

S = 4096  # 4x supersample of the 1024 master

# --- Netcloud blue family (subtle vertical gradient) -----------------------
PRIMARY_TOP = (84, 78, 255)    # #544EFF
PRIMARY_BOT = (56, 50, 226)    # #3832E2
WHITE = (255, 255, 255)

# --- 1) rounded-square tile with gradient ----------------------------------
radius = int(S * 0.212)
tile_mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(tile_mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=radius, fill=255)

lg = Image.linear_gradient("L").resize((S, S), Image.BICUBIC)
top_img = Image.new("RGB", (S, S), PRIMARY_TOP)
bot_img = Image.new("RGB", (S, S), PRIMARY_BOT)
tile = Image.composite(bot_img, top_img, lg).convert("RGBA")
tile.putalpha(tile_mask)

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(tile, (0, 0), tile)

# --- 2) soft top sheen (clipped to the tile) -------------------------------
sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sheen).ellipse(
    (-S * 0.15, -S * 0.32, S * 1.15, S * 0.52), fill=(255, 255, 255, 40))
sheen = sheen.filter(ImageFilter.GaussianBlur(S * 0.055))
sa = sheen.split()[3]
sa = Image.composite(sa, Image.new("L", (S, S), 0), tile_mask)
sheen.putalpha(sa)
img = Image.alpha_composite(img, sheen)

# --- 3) bold white "M↓" glyph ---------------------------------------------
draw = ImageDraw.Draw(img)
OX, OY = -0.014, -0.015  # nudge so the glyph's bbox is optically centered


def u(x, y):
    return ((x + OX) * S, (y + OY) * S)


def round_stroke(pts, w, fill):
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=fill, width=w)
    r = w / 2.0
    for p in pts:
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=fill)


W = int(S * 0.095)  # stroke width

# M: left stem up, V down to middle, up to right stem, right stem down
m = [u(0.19, 0.70), u(0.19, 0.33), u(0.42, 0.60),
     u(0.65, 0.33), u(0.65, 0.70)]
round_stroke(m, W, WHITE)

# ↓: vertical stem (round top) + filled arrowhead
ax = 0.80
round_stroke([u(ax, 0.34), u(ax, 0.55)], W, WHITE)
head = [u(0.715, 0.53), u(0.885, 0.53), u(0.80, 0.70)]
draw.polygon(head, fill=WHITE)

# --- 4) downscale chain + save ---------------------------------------------
cur = img
pngs = {}
for sz in (1024, 512, 256, 128, 64, 32, 16):
    cur = cur.resize((sz, sz), Image.LANCZOS)
    pngs[sz] = cur

pngs[1024].save(OUT / "logo-1024.png")

iconset = OUT / "AppIcon.iconset"
iconset.mkdir(parents=True, exist_ok=True)
iconset_map = {
    16:   ["icon_16x16.png"],
    32:   ["icon_32x32.png", "icon_16x16@2x.png"],
    64:   ["icon_32x32@2x.png"],
    128:  ["icon_128x128.png"],
    256:  ["icon_256x256.png", "icon_128x128@2x.png"],
    512:  ["icon_512x512.png", "icon_256x256@2x.png"],
    1024: ["icon_512x512@2x.png"],
}
for sz, names in iconset_map.items():
    for n in names:
        pngs[sz].save(iconset / n)

print("wrote", OUT / "logo-1024.png")
print("iconset at", iconset)
