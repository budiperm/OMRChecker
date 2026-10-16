"""Draws the app icon: a blue tile with an answer sheet (LJK) whose corner
markers and filled bubbles echo the real form, plus a green check badge.
Writes icon.ico (16-256 px, a simpler sheet below 40 px), icon.png and
logo.png next to this file. Run: python assets/make_icon.py"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
S = 1024  # drawing size; scaled down with LANCZOS
TOP, BOTTOM = (0x23, 0x86, 0xF0), (0x00, 0x4C, 0xA3)
INK, BUBBLE, GREEN = (0x1C, 0x2B, 0x45), (0xB9, 0xC7, 0xDA), (0x1F, 0xA2, 0x4A)


def tile():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line([(0, y), (S, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)
    return img


def sheet(img, simple):
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 230, 150, 794, 874
    # soft shadow, then the paper
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0 + 14, y0 + 22, x1 + 14, y1 + 22], radius=44, fill=(0, 20, 60, 90))
    img.alpha_composite(shadow)
    d.rounded_rectangle([x0, y0, x1, y1], radius=44, fill=(255, 255, 255, 255))
    if simple:  # 16-32 px: two big rows of bubbles, one filled each
        for r, filled in enumerate((1, 2)):
            cy = 320 + r * 200
            for c in range(3):
                cx = 340 + c * 172
                box = [cx - 62, cy - 62, cx + 62, cy + 62]
                d.ellipse(box, fill=INK if c == filled else None, outline=None if c == filled else BUBBLE, width=26)
        return
    m = 54  # LJK corner markers
    for cx, cy in ((x0 + 50, y0 + 50), (x1 - 50 - m, y0 + 50), (x0 + 50, y1 - 50 - m), (x1 - 50 - m, y1 - 50 - m)):
        d.rectangle([cx, cy, cx + m, cy + m], fill=INK)
    for r, filled in enumerate((0, 2, 3, 1)):
        cy = 300 + r * 118
        d.rounded_rectangle([300, cy - 14, 352, cy + 14], radius=14, fill=BUBBLE)  # question number
        for c in range(4):
            cx = 430 + c * 92
            box = [cx - 34, cy - 34, cx + 34, cy + 34]
            if c == filled:
                d.ellipse(box, fill=INK)
            else:
                d.ellipse(box, outline=BUBBLE, width=12)


def badge(img, simple):
    d = ImageDraw.Draw(img)
    cx, cy, r = (760, 770, 190) if not simple else (775, 775, 185)
    d.ellipse([cx - r - 22, cy - r - 22, cx + r + 22, cy + r + 22], fill=(255, 255, 255, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN)
    k = r / 190
    pts = [(cx - 88 * k, cy + 4 * k), (cx - 22 * k, cy + 70 * k), (cx + 96 * k, cy - 62 * k)]
    d.line(pts, fill=(255, 255, 255, 255), width=round(46 * k), joint="curve")
    for x, y in (pts[0], pts[2]):
        w = 23 * k
        d.ellipse([x - w, y - w, x + w, y + w], fill=(255, 255, 255, 255))


def draw(simple=False):
    img = tile()
    sheet(img, simple)
    badge(img, simple)
    return img


def main():
    full, simple = draw(), draw(simple=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [(simple if s < 40 else full).resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(HERE / "icon.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    full.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    full.resize((40, 40), Image.LANCZOS).save(HERE / "logo.png")  # sidebar
    full.resize((512, 512), Image.LANCZOS).save(HERE / "icon_512.png")


if __name__ == "__main__":
    main()
