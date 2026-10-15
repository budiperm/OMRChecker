"""Template made from the printer's blank Medion LJK (vector PDF, the real
source of the sheets), then used to read:

- simulated flatbed scans of it, pencilled with random answers;
- the CamScanner photo of a filled sheet (tests_gui/data/ljk_medion_terisi.pdf).

The printed circles (vector drawings in the PDF) are the independent ground
truth for where every bubble is.

Run: python -m pytest tests_gui
"""

import csv
import random
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
import test_medion_ljk as photo  # noqa: E402
import ujian  # noqa: E402

from testdata import needs  # noqa: E402

pytestmark = [needs("ljk_medion_cetak_kosong.pdf"), needs("ljk_medion_terisi.pdf")]

BLANK = Path(__file__).parent / "data" / "ljk_medion_cetak_kosong.pdf"
PT = 150 / 72  # vector PDFs are rendered at 150 DPI = template pixels
pymupdf = pytest.importorskip("pymupdf")
SEAT = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ", "123456789", "0123456789"]


@pytest.fixture(scope="module")
def sheet():
    return tb.prepare_sheet(tb.load_image(BLANK), source_name=BLANK.name)


@pytest.fixture(scope="module")
def detected(sheet):
    return tb.detect_blocks(sheet)


def label(bubbles, blocks):
    """The teacher's few steps in the editor for this sheet."""
    blocks = [tb.Block(**vars(b)) for b in blocks]
    rename = {"III": "Motivasi", "IV": "TYPE", "V": "III"}
    for b in blocks:
        if b.kind == tb.KIND_MCQ:
            b.section = rename.get(b.section, b.section)
    seat = next(b for b in blocks if (b.kind, b.rows, b.cols) == (tb.KIND_DIGITS, 10, 5))
    parts = tb.split_block(seat, "column", bubbles)
    for part, values in zip(parts, SEAT):
        tb.set_kind(part, tb.KIND_CUSTOM, list(values), horizontal=False)
        part.group = "KodeDuduk"
    blocks.remove(seat)
    blocks += parts
    pairs = sorted((b for b in blocks if (b.rows, b.cols) == (2, 1) and b.kind == tb.KIND_CUSTOM), key=lambda b: b.y0)
    for b, (name, values) in zip(pairs, (("JK", "LP"), ("KodeBuku", "XY"))):
        tb.set_kind(b, tb.KIND_CUSTOM, list(values), horizontal=False)
        b.group = name
    tb.number_mcq_blocks(blocks)
    return tb.sort_blocks(blocks)


@pytest.fixture(scope="module")
def library(tmp_path_factory, sheet, detected):
    bubbles, blocks = detected
    blocks = label(bubbles, blocks)
    template, problems = tb.build_template(blocks, sheet)
    assert problems == []
    lib = ujian.save_to_library("Medion cetak", sheet, template, blocks, tmp_path_factory.mktemp("lib"))
    return lib, blocks


def test_auto_detection_finds_every_field(detected):
    _, blocks = detected
    parts = {}
    for b in blocks:
        if b.kind == tb.KIND_MCQ:
            parts[b.section] = parts.get(b.section, 0) + b.field_count
    assert parts == {"I": 130, "II": 88, "III": 10, "IV": 1, "V": 8}
    others = sorted((b.kind, b.rows, b.cols, b.group) for b in blocks if b.kind != tb.KIND_MCQ)
    assert others == [
        (tb.KIND_CUSTOM, 2, 1, ""),  # gender L/P: big unlettered circles
        (tb.KIND_CUSTOM, 2, 1, ""),  # booklet code X/Y: bigger circles
        (tb.KIND_CUSTOM, 26, 20, "Nama"),
        (tb.KIND_DIGITS, 10, 5, ""),  # seat code, split by the user
        (tb.KIND_DIGITS, 10, 6, "TglLahir"),
        (tb.KIND_IGNORE, 1, 2, ""),  # round letters in the logo
        (tb.KIND_IGNORE, 3, 5, ""),  # "how to fill in" example
    ]


def test_blank_source_sheet_is_excluded(sheet, library):
    lib, _ = library
    assert sheet.source_blank  # nothing pencilled on the printer's PDF
    assert ujian.read_library_template(lib).source == BLANK.name


def test_template_covers_every_printed_circle(library):
    _, blocks = library
    page = pymupdf.open(str(BLANK))[0]
    circles = [
        d["rect"] for d in page.get_drawings()
        if d["type"] == "s" and 7 < d["rect"].width < 14 and abs(d["rect"].width - d["rect"].height) < 0.5
    ]  # fmt: skip
    example = (220, 160, 370, 250)  # "Cara Menjawab" (ignored)
    centres = [((r.x0 + r.x1) / 2 * PT, (r.y0 + r.y1) / 2 * PT) for r in circles]
    centres = [c for c in centres if not (example[0] <= c[0] <= example[2] and example[1] <= c[1] <= example[3])]
    grid = np.array([pos for b in blocks if b.kind != tb.KIND_IGNORE for _, pos in positions(b)])
    worst = max(float(np.min(np.hypot(grid[:, 0] - x, grid[:, 1] - y))) for x, y in centres)
    assert len(centres) > 1250
    assert worst < 3.0, f"a printed bubble is {worst:.1f}px from the template"


def positions(b):
    """((field index, value), (x, y)) of every bubble of a block."""
    out = []
    for r in range(b.rows):
        for c in range(b.cols):
            field, value = (r, b.values[c]) if b.horizontal else (c, b.values[r])
            out.append(((field, value), (b.x0 + c * b.gap_x + b.bw / 2, b.y0 + r * b.gap_y + b.bh / 2)))
    return out


def fill_randomly(blocks, rnd):
    """Pick a value for every field; returns expected columns and marks."""
    expected, marks = {}, []
    groups = {}
    for b in blocks:
        if b.kind == tb.KIND_IGNORE:
            continue
        pos = dict(positions(b))
        prefix = tb.section_prefix(b.section)
        for f in range(b.field_count):
            if b.kind == tb.KIND_MCQ:
                q = f"{prefix}{b.start + f}"
                if rnd.random() < 0.1:
                    expected[q] = ""
                    continue
                v = rnd.choice(b.values)
                expected[q] = v
            else:
                v = rnd.choice(b.values)
                groups.setdefault(b.group, []).append((b.x0 + f * (b.gap_x if not b.horizontal else 0), v))
            marks.append(pos[(f, v)])
    for name, parts in groups.items():
        expected[name] = "".join(v for _, v in sorted(parts))
    return expected, marks


@pytest.mark.parametrize("k, scan", enumerate([
    {"jpeg": 92},
    {"angle": 1.2, "dx": -30, "dy": 20, "noise": 4, "jpeg": 85},
    {"angle": -1.5, "scale": 0.97, "dx": 25, "noise": 5, "jpeg": 80},
]))  # fmt: skip
def test_reads_simulated_flatbed_scans(tmp_path, library, k, scan):
    lib, blocks = library
    rnd = random.Random(k)
    expected, marks = fill_randomly(blocks, rnd)
    pix = pymupdf.open(str(BLANK))[0].get_pixmap(dpi=200)
    img = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n), cv2.COLOR_RGB2BGR)
    z = 200 / 150
    for x, y in marks:
        shade = rnd.randint(30, 70)
        cv2.ellipse(img, (int(x * z), int(y * z)), (11, 10), rnd.randint(0, 180), 0, 360, (shade,) * 3, -1, cv2.LINE_AA)
    # the scanner bed is larger than the sheet: white around the paper
    img = cv2.copyMakeBorder(img, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    img = synth.distort(img, seed=k, **scan)
    scans = tmp_path / "scan"
    scans.mkdir()
    cv2.imencode(".jpg", img)[1].tofile(str(scans / "peserta.jpg"))
    out = tmp_path / "hasil"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out), "--template", str(lib)],
        capture_output=True, text=True, timeout=600,
    )
    log = (out / "omrchecker_log.txt").read_text(encoding="utf-8") if out.exists() else ""
    assert proc.returncode == 0, log[-3000:]
    rows, errors = ujian.read_results(out)
    assert len(rows) == 1 and not errors, log[-3000:]
    wrong = [f"{c}: {rows[0][c]!r} != {v!r}" for c, v in expected.items() if rows[0][c] != v]
    assert not wrong, "\n".join(wrong[:20])


def test_cut_off_corner_square_is_flagged_not_misread(tmp_path, library):
    """A sheet shifted so far that a corner square is cut off must end up as
    'not readable' (rescan), never aligned on the orientation mark beside it."""
    lib, _ = library
    pix = pymupdf.open(str(BLANK))[0].get_pixmap(dpi=200)
    img = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n), cv2.COLOR_RGB2BGR)
    img = synth.distort(img, angle=1.2, dx=-30, dy=20, jpeg=85)
    scans = tmp_path / "scan"
    scans.mkdir()
    cv2.imencode(".jpg", img)[1].tofile(str(scans / "terpotong.jpg"))
    out = tmp_path / "hasil"
    subprocess.run([sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out), "--template", str(lib)],
                   capture_output=True, timeout=600)  # fmt: skip
    rows, errors = ujian.read_results(out)
    assert rows == [] and [e["file_id"] for e in errors] == ["terpotong.jpg"]
    res = ujian.score_results(rows, errors, ujian.Exam(), ujian.read_library_template(lib).sections)
    assert res[0].unreadable and "tidak terbaca" in res[0].flags[0]


def test_reads_camscanner_photo(tmp_path, library):
    """The phone photo is bent; four corner squares cannot undo that, so the
    most bent areas can misread (found: 9 of 237 questions). Identity fields
    must be exact and nearly all answers right. Flatbed scans have no bend
    (see test_reads_simulated_flatbed_scans: all exact)."""
    lib, _ = library
    scans = tmp_path / "scan"
    scans.mkdir()
    (scans / "siswa.pdf").write_bytes(photo.SCAN.read_bytes())
    out = tmp_path / "hasil"
    subprocess.run([sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out), "--template", str(lib)],
                   capture_output=True, timeout=600)  # fmt: skip
    rows, errors = ujian.read_results(out)
    assert len(rows) == 1 and not errors
    row = rows[0]
    for col, value in photo.EXPECTED.items():
        assert row[col].strip() == value, col
    info = ujian.read_library_template(lib)
    right = total = 0
    for part, labels in info.sections.items():
        for i, q in enumerate(labels):
            want = photo.ANSWERS[part][i] if i < len(photo.ANSWERS[part]) else ""
            right += row[q] == want
            total += 1
    assert right / total >= 0.95, f"{right}/{total}"


def test_upside_down_sheet_is_turned(tmp_path, library):
    """An ADF often feeds a sheet upside down: the four corner squares are
    then in the same places, so the blank sheet decides which way is up."""
    lib, blocks = library
    rnd = random.Random(42)
    expected, marks = fill_randomly(blocks, rnd)
    pix = pymupdf.open(str(BLANK))[0].get_pixmap(dpi=200)
    img = cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n), cv2.COLOR_RGB2BGR)
    for x, y in marks:
        cv2.ellipse(img, (int(x * 4 / 3), int(y * 4 / 3)), (11, 10), 0, 0, 360, (50, 50, 50), -1, cv2.LINE_AA)
    img = cv2.copyMakeBorder(img, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    img = synth.distort(cv2.rotate(img, cv2.ROTATE_180), angle=0.8, dx=15, jpeg=85)
    scans = tmp_path / "scan"
    scans.mkdir()
    cv2.imencode(".jpg", img)[1].tofile(str(scans / "terbalik.jpg"))
    out = tmp_path / "hasil"
    subprocess.run([sys.executable, str(ROOT / "gui.py"), "--process", str(scans), str(out), "--template", str(lib)],
                   capture_output=True, timeout=600)  # fmt: skip
    rows, _ = ujian.read_results(out)
    assert len(rows) == 1
    wrong = [c for c, v in expected.items() if rows[0][c] != v]
    assert not wrong, wrong[:10]
    assert "upside down" in (out / "omrchecker_log.txt").read_text(encoding="utf-8")


def test_old_templates_are_upgraded(tmp_path, library):
    """Templates saved before the upside-down check get it when used."""
    import json
    import shutil

    lib, _ = library
    old = tmp_path / "lama"
    shutil.copytree(lib, old)
    t = json.loads((old / "template.json").read_text())
    del t["preProcessors"][0]["options"]["orientationReference"]
    (old / "template.json").write_text(json.dumps(t))
    (old / tb.ORIENTATION_FILENAME).unlink()
    assert ujian.upgrade_template(old)
    t = json.loads((old / "template.json").read_text())
    assert t["preProcessors"][0]["options"]["orientationReference"] == tb.ORIENTATION_FILENAME
    assert (old / tb.ORIENTATION_FILENAME).exists()
    assert not ujian.upgrade_template(old)  # nothing left to do
