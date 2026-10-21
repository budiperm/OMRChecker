"""Synthetic answer sheets (LJK) for testing the template builder.

The layout mimics a bought Indonesian LJK: red ink, letters/digits printed
inside the bubbles, write-in boxes above the number columns, a round logo,
question numbers beside each row and questions grouped by five.
Drawn at 300 DPI on A4 (2480 x 3508 px) like a real scan.
"""

import random
from dataclasses import dataclass, field

import cv2
import numpy as np

W, H = 2480, 3508
RED = (70, 70, 225)  # BGR
BLACK = (20, 20, 20)
R = 26  # bubble radius (≈ 4.4 mm)
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class Layout:
    # label -> {value: (cx, cy)} in 300 DPI page pixels
    fields: dict = field(default_factory=dict)
    # region name -> (x0, y0, x1, y1) bounding the bubbles of that region
    regions: dict = field(default_factory=dict)
    questions: int = 0


def _bubble(img, cx, cy, text):
    cv2.circle(img, (cx, cy), R, RED, 3, cv2.LINE_AA)
    scale = 0.9
    (tw, th), _ = cv2.getTextSize(text, FONT, scale, 2)
    cv2.putText(img, text, (cx - tw // 2, cy + th // 2), FONT, scale, RED, 2, cv2.LINE_AA)


def _text(img, x, y, text, scale=1.2, color=BLACK, thick=2):
    cv2.putText(img, text, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def _digit_block(img, layout, name, x0, y0, digits, gap=66, boxes=True):
    """Columns of 0-9 bubbles; one field per column."""
    if boxes:  # write-in boxes above the columns (bigger than bubbles)
        for d in range(digits):
            cx = x0 + d * gap
            cv2.rectangle(img, (cx - 37, y0 - 110), (cx + 37, y0 - 36), RED, 3)
    for d in range(digits):
        cx = x0 + d * gap
        values = {}
        for v in range(10):
            cy = y0 + v * gap
            _bubble(img, cx, cy, str(v))
            values[str(v)] = (cx, cy)
        layout.fields[f"{name}_{d + 1}"] = values
    layout.regions[name] = (x0 - R, y0 - R, x0 + (digits - 1) * gap + R, y0 + 9 * gap + R)


def make_blank(seed=0):
    rnd = random.Random(seed)
    img = np.full((H, W, 3), 255, np.uint8)
    layout = Layout()

    # Header, logo and frame
    cv2.rectangle(img, (80, 80), (W - 80, H - 80), RED, 4)
    cv2.circle(img, (260, 260), 120, RED, 6)  # round school logo
    _text(img, 200, 275, "SMP", 1.4, RED, 3)
    _text(img, 520, 230, "LEMBAR JAWABAN KOMPUTER", 2.2, BLACK, 5)
    _text(img, 520, 310, "UJIAN SEKOLAH - Gunakan pensil 2B", 1.2)
    _text(img, 160, 470, "NAMA", 1.2)
    for i in range(20):  # name boxes, no bubbles
        cv2.rectangle(img, (380 + i * 90, 420), (450 + i * 90, 490), RED, 3)

    # NIS: 10 digits
    _text(img, 160, 600, "NOMOR INDUK SISWA (NIS)", 1.1)
    _digit_block(img, layout, "NIS", 200, 760, 10)
    # Kode soal: 2 digits
    _text(img, 1000, 600, "KODE SOAL", 1.1)
    _digit_block(img, layout, "KODE", 1040, 760, 2)
    # Tanggal lahir: DD MM YY as three blocks
    _text(img, 1350, 600, "TANGGAL LAHIR", 1.1)
    for k, (name, x) in enumerate((("TGL", 1390), ("BLN", 1640), ("THN", 1890))):
        _text(img, x - 10, 640, name, 0.9)
        _digit_block(img, layout, name, x, 760, 2)

    # Answers: 4 columns x 15 questions, grouped by five
    _text(img, 160, 1580, "JAWABAN", 1.4, BLACK, 3)
    q = 1
    col_x = [300, 860, 1420, 1980]
    for cx0 in col_x:
        y = 1700
        x_first = cx0
        for row in range(15):
            if row and row % 5 == 0:
                y += 40  # extra space between groups of five
            _text(img, cx0 - 130, y + 14, f"{q:>2}.", 1.0)
            values = {}
            for o, letter in enumerate("ABCDE"):
                bx = x_first + o * 72
                _bubble(img, bx, y, letter)
                values[letter] = (bx, y)
            layout.fields[f"q{q}"] = values
            q += 1
            y += 70
    layout.questions = q - 1
    layout.regions["ANSWERS"] = (col_x[0] - R, 1700 - R, col_x[-1] + 4 * 72 + R, y)

    # A little print noise so it is not perfectly clean
    noise = np.random.default_rng(seed).normal(0, 3, img.shape)
    img = np.clip(img.astype(np.int16) + noise.astype(np.int16), 0, 255).astype(np.uint8)
    _ = rnd
    return img, layout


def random_responses(layout, seed, blank_rate=0.1):
    rnd = random.Random(seed)
    responses = {}
    for label, values in layout.fields.items():
        if label.startswith("q") and rnd.random() < blank_rate:
            continue  # unanswered question
        responses[label] = rnd.choice(sorted(values))
    return responses


def fill(img, layout, responses, seed=0):
    """Pencil marks: dark grey ellipses with a little jitter."""
    rnd = random.Random(seed)
    out = img.copy()
    for label, value in responses.items():
        cx, cy = layout.fields[label][value]
        jx, jy = rnd.randint(-3, 3), rnd.randint(-3, 3)
        shade = rnd.randint(35, 70)
        cv2.ellipse(
            out, (cx + jx, cy + jy), (R - 5, R - 6), rnd.randint(0, 180), 0, 360,
            (shade, shade, shade), -1, cv2.LINE_AA,
        )
    return out


def cross(img, layout, responses, seed=0, thick=3, shade=40):
    """Thin ballpoint crosses (X) over the chosen bubbles instead of shading;
    number blocks shaded as usual. Read as blank at the normal sensitivity."""
    rnd = random.Random(seed)
    out = fill(img, layout, {k: v for k, v in responses.items() if not k.startswith("q")}, seed)
    for label, value in responses.items():
        if not label.startswith("q"):
            continue
        cx, cy = layout.fields[label][value]
        cx, cy, a = cx + rnd.randint(-3, 3), cy + rnd.randint(-3, 3), int(R * 0.7)
        for d in (1, -1):
            cv2.line(out, (cx - a, cy - d * a), (cx + a, cy + d * a), (shade,) * 3, thick, cv2.LINE_AA)
    return out


def distort(img, angle=0.0, dx=0, dy=0, scale=1.0, noise=0.0, jpeg=None, seed=0):
    """Simulate how a sheet lands on the scanner glass."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[:, 2] += (dx, dy)
    out = cv2.warpAffine(img, m, (w, h), borderValue=(255, 255, 255))
    if noise:
        rng = np.random.default_rng(seed)
        out = np.clip(out + rng.normal(0, noise, out.shape), 0, 255).astype(np.uint8)
    if jpeg:
        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
        out = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return out


def expected_row(layout, responses):
    """Values OMRChecker should output, grouped like the builder's columns."""
    row = {}
    for q in range(1, layout.questions + 1):
        row[f"q{q}"] = responses.get(f"q{q}", "")
    for group, prefix in (("NIS", "NIS"), ("KodeSoal", "KODE")):
        n = sum(1 for k in layout.fields if k.startswith(prefix + "_"))
        row[group] = "".join(responses[f"{prefix}_{i}"] for i in range(1, n + 1))
    row["TglLahir"] = "".join(
        responses[f"{p}_{i}"] for p in ("TGL", "BLN", "THN") for i in (1, 2)
    )
    return row
