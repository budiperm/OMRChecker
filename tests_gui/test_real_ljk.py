"""Template builder on a real answer sheet (LJK SMP Negeri 3 Sekampung Udik):
blue ink, small tightly packed bubbles touching box borders, four black
corner squares, name (space + A-Z), participant number, exam code, birth
date and 100 questions.

Ground truth comes from the PDF itself, independent of the detector: every
bubble is a vector circle (9.1 pt) with its letter/digit as text inside.

Run: python -m pytest tests_gui
"""

import csv
import dataclasses
import random
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

import synth_ljk as synth  # noqa: E402
import template_builder as tb  # noqa: E402

from testdata import needs  # noqa: E402

pytestmark = [needs("ljk_kosong_smpn3.pdf")]

PDF = Path(__file__).parent / "data" / "ljk_kosong_smpn3.pdf"
DPI = 150  # tb.load_image renders PDFs at 150 DPI = template pixels
PT = DPI / 72

pymupdf = pytest.importorskip("pymupdf")

# Sections of the sheet in PDF points: (x0, y0, x1, y1) -> output column
SECTIONS = {
    "Nama": (40, 190, 410, 525),
    "NIS": (412, 190, 552, 320),
    "KodeSoal": (412, 390, 458, 525),
    "TglLahir": (470, 390, 552, 525),
}


def ground_truth():
    """{column: [[(value, cx, cy) per option] per field, left to right]} plus
    answers {question: {letter: (cx, cy)}}, in 150 DPI pixels."""
    page = pymupdf.open(str(PDF))[0]
    circles = [
        d["rect"]
        for d in page.get_drawings()
        if d["type"] == "f" and 8.5 < d["rect"].width < 9.3 and 8.5 < d["rect"].height < 9.3
    ]
    words = page.get_text("words")

    def value(r):
        inside = [
            w[4] for w in words
            if r.x0 <= (w[0] + w[2]) / 2 <= r.x1 and r.y0 <= (w[1] + w[3]) / 2 <= r.y1
        ]  # fmt: skip
        return inside[0] if inside else " "  # empty bubble = space in names

    bubbles = [(value(r), (r.x0 + r.x1) / 2 * PT, (r.y0 + r.y1) / 2 * PT, r) for r in circles]

    fields = {}
    for name, (x0, y0, x1, y1) in SECTIONS.items():
        inside = [b for b in bubbles if x0 <= b[3].x0 <= x1 and y0 <= b[3].y0 <= y1]
        columns = {}
        for v, cx, cy, r in inside:
            columns.setdefault(round(r.x0), []).append((v, cx, cy))
        fields[name] = [sorted(col, key=lambda b: b[2]) for _, col in sorted(columns.items())]

    answers = {}
    rest = [b for b in bubbles if b[3].y0 > 540]
    xs = sorted({round(b[3].x0) for b in rest})
    groups = [xs[i : i + 5] for i in range(0, len(xs), 5)]  # 5 answer columns
    for g, group_xs in enumerate(groups):
        col = [b for b in rest if round(b[3].x0) in group_xs]
        rows = sorted({round(b[3].y0) for b in col})
        for r, y in enumerate(rows):
            q = g * len(rows) + r + 1
            answers[f"q{q}"] = {b[0]: (b[1], b[2]) for b in col if round(b[3].y0) == y}
    return fields, answers, len(circles)


@pytest.fixture(scope="module")
def truth():
    return ground_truth()


@pytest.fixture(scope="module")
def sheet():
    return tb.prepare_sheet(tb.load_image(PDF))


@pytest.fixture(scope="module")
def detected(sheet):
    return tb.detect_blocks(sheet.page)[1]


def test_ground_truth_is_complete(truth):
    fields, answers, total = truth
    assert total == 1510
    assert [len(fields[k]) for k in SECTIONS] == [30, 11, 3, 6]
    assert len(answers) == 100 and all(sorted(a) == list("ABCDE") for a in answers.values())


def test_corner_markers_found(sheet):
    assert sheet.uses_markers
    assert sheet.preprocessors()[0]["name"] == "AlignOnMarkers"
    xs = sorted(x for x, _ in sheet.markers)
    ys = sorted(y for _, y in sheet.markers)
    # squares at (45.6, 160.1) and (537.6, 796.1) pt, 9.4 pt wide
    assert xs[0] == pytest.approx(50.3 * PT, abs=2) and xs[-1] == pytest.approx(542.3 * PT, abs=2)
    assert ys[0] == pytest.approx(164.8 * PT, abs=2) and ys[-1] == pytest.approx(800.8 * PT, abs=2)


def test_blocks_and_suggestions(detected):
    summary = sorted((b.kind, b.rows, b.cols, b.group) for b in detected if b.kind != tb.KIND_MCQ)
    assert summary == [
        (tb.KIND_CUSTOM, 27, 30, "Nama"),
        (tb.KIND_DIGITS, 10, 3, "KodeSoal"),
        (tb.KIND_DIGITS, 10, 6, "TglLahir"),
        (tb.KIND_DIGITS, 10, 11, "NIS"),
        (tb.KIND_IGNORE, 1, 2, ""),  # round letters in the heading
    ]
    mcq = sorted((b.start, b.rows, b.cols) for b in detected if b.kind == tb.KIND_MCQ)
    assert mcq == [(1, 20, 5), (21, 20, 5), (41, 20, 5), (61, 20, 5), (81, 20, 5)]


def grid_positions(block):
    """(value, cx, cy) of every bubble the template will read in a block."""
    out = []
    for r in range(block.rows):
        for c in range(block.cols):
            v = block.values[c] if block.horizontal else block.values[r]
            out.append((v, block.x0 + c * block.gap_x + block.bw / 2,
                        block.y0 + r * block.gap_y + block.bh / 2))  # fmt: skip
    return out


def test_every_bubble_mapped_to_right_value(truth, detected):
    fields, answers, _ = truth
    expected = [b for cols in fields.values() for col in cols for b in col]
    expected += [(v, x, y) for opts in answers.values() for v, (x, y) in opts.items()]
    template = [p for b in detected for p in grid_positions(b)]
    pts = np.array([(x, y) for _, x, y in template])
    worst, wrong = 0.0, []
    for v, x, y in expected:
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        i = int(np.argmin(d))
        worst = max(worst, float(d[i]))
        if template[i][0] != v:
            wrong.append((v, template[i][0], round(x), round(y)))
    assert not wrong, wrong[:10]
    assert worst < 3.0, f"template bubble up to {worst:.1f}px off the printed bubble"


def render_filled(fields, answers, responses, name):
    """Render the PDF at 200 DPI like a scanner and pencil in the answers."""
    page = pymupdf.open(str(PDF))[0]
    pix = page.get_pixmap(dpi=200)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR)
    k = 200 / DPI
    rnd = random.Random(name)

    def mark(x, y):
        shade = rnd.randint(30, 70)
        cv2.ellipse(img, (int(x * k) + rnd.randint(-1, 1), int(y * k) + rnd.randint(-1, 1)),
                    (10, 9), rnd.randint(0, 180), 0, 360, (shade,) * 3, -1, cv2.LINE_AA)  # fmt: skip

    for column, value in responses.items():
        if column.startswith("q"):
            mark(*answers[column][value])
        else:
            for col, ch in zip(fields[column], value):
                v, x, y = next(b for b in col if b[0] == ch)
                mark(x, y)
    return img


SCANS = {
    "lurus.jpg": {"jpeg": 90},
    "geser.jpg": {"dx": 45, "dy": -35, "jpeg": 85},
    "miring.jpg": {"angle": 1.5, "dx": -30, "dy": 25, "noise": 5, "jpeg": 85},
    "miring_kiri_kecil.jpg": {"angle": -2.0, "scale": 0.97, "noise": 4, "jpeg": 80},
}


def test_end_to_end_reads_filled_sheets(tmp_path, truth, sheet, detected):
    fields, answers, _ = truth
    template, problems = tb.build_template(detected, sheet)
    assert problems == []
    rnd = random.Random(7)
    key = [rnd.choice("ABCDE") for _ in range(100)]
    evaluation = tb.build_evaluation(tb.question_labels(detected), key)
    exam = tmp_path / "ujian"
    # the blank scan the template came from ends up in the exam folder too
    sheet = dataclasses.replace(sheet, source_name="LJK_kosong.pdf")
    template, _ = tb.build_template(detected, sheet)
    written = tb.save_template_folder(exam, sheet, template, evaluation)
    assert tb.REFERENCE_FILENAME not in written  # aligned on corner squares instead
    shutil.copy(PDF, exam / "LJK_kosong.pdf")

    names = ["BUDI SANTOSO", "SITI AMINAH", "ANDI", "MUHAMMAD RIZKY PRATAMA"]
    expected = {}
    for k, (scan, params) in enumerate(SCANS.items()):
        responses = {
            "Nama": names[k],
            "NIS": "".join(rnd.choice("0123456789") for _ in range(11)),
            "KodeSoal": "".join(rnd.choice("0123456789") for _ in range(3)),
            "TglLahir": rnd.choice(["170805", "010110", "311209", "250511"]),
        }
        for q in range(1, 101):
            if rnd.random() > 0.08:  # a few questions left blank
                responses[f"q{q}"] = rnd.choice("ABCDE")
        img = render_filled(fields, answers, responses, scan)
        img = synth.distort(img, seed=k, **params)
        cv2.imencode(".jpg", img)[1].tofile(str(exam / scan))
        row = {c: responses.get(c, "") for c in ("Nama", "NIS", "KodeSoal", "TglLahir")}
        row.update({f"q{q}": responses.get(f"q{q}", "") for q in range(1, 101)})
        row["score"] = sum(responses.get(f"q{q}") == key[q - 1] for q in range(1, 101))
        expected[scan] = row

    out = tmp_path / "hasil"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "gui.py"), "--process", str(exam), str(out)],
        capture_output=True, text=True, timeout=600,
    )
    log = (out / "omrchecker_log.txt").read_text(encoding="utf-8") if out.exists() else ""
    assert proc.returncode == 0, log[-3000:] + proc.stderr[-2000:]
    results = list((out / "Results").glob("Results_*.csv"))
    assert len(results) == 1, log[-3000:]
    with open(results[0], newline="", encoding="utf-8") as f:
        rows = {r["file_id"]: r for r in csv.DictReader(f)}
    assert set(rows) == set(SCANS), log[-3000:]  # blank sheet not graded

    mismatches = []
    for scan, exp in expected.items():
        for col, value in exp.items():
            got = rows[scan][col]
            if col == "score":
                got = float(got)
            elif col == "Nama":
                got = got.rstrip()
            if got != value:
                mismatches.append(f"{scan} {col}: got {got!r}, expected {value!r}")
    assert not mismatches, "\n".join(mismatches[:30])
