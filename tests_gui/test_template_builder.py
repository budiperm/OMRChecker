"""Tests for template_builder: detection on synthetic LJK, template output,
and an end-to-end run through OMRChecker on filled, distorted scans.

Run: python -m pytest tests_gui
"""

import csv
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]

import synth_ljk as synth  # noqa: E402
import template_builder as tb  # noqa: E402

SCALE = 1240 / synth.W  # synthetic 300 DPI pixels -> template pixels

# Region of the synthetic sheet -> output column name a user would type
GROUPS = {
    "NIS": "NIS",
    "KODE": "KodeSoal",
    "TGL": "TglLahir",
    "BLN": "TglLahir",
    "THN": "TglLahir",
}


@pytest.fixture(scope="module")
def blank():
    img, layout = synth.make_blank()
    sheet = tb.prepare_sheet(img)
    assert not sheet.uses_markers  # synthetic sheet: no corner squares
    return img, layout, sheet.page_dims, sheet


@pytest.fixture(scope="module")
def detected(blank):
    _, _, _, sheet = blank
    return tb.detect_blocks(sheet.page)


def region_of(block, layout):
    """Name of the synthetic region containing the block's centre."""
    cx = (block.x0 + block.x1) / 2 / SCALE
    cy = (block.y0 + block.y1) / 2 / SCALE
    for name, (x0, y0, x1, y1) in layout.regions.items():
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return name
    return None


def label_like_user(blocks, layout):
    """What the user does in the editor: name the number blocks."""
    for b in blocks:
        region = region_of(b, layout)
        if region in GROUPS:
            tb.set_kind(b, tb.KIND_DIGITS)
            b.group = GROUPS[region]
    return blocks


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detects_every_bubble(blank, detected):
    _, layout, _, _ = blank
    bubbles, blocks = detected
    expected = sum(len(v) for v in layout.fields.values())
    in_blocks = sum(b.rows * b.cols for b in blocks)
    assert in_blocks == expected


def test_ignores_boxes_logo_and_text(blank, detected):
    _, layout, _, _ = blank
    _, blocks = detected
    for b in blocks:
        assert region_of(b, layout) is not None, f"unexpected block {b}"


def test_number_blocks_are_digit_columns(blank, detected):
    _, layout, _, _ = blank
    _, blocks = detected
    shapes = sorted(
        (region_of(b, layout), b.rows, b.cols, b.kind)
        for b in blocks
        if region_of(b, layout) != "ANSWERS"
    )
    assert shapes == [
        ("BLN", 10, 2, tb.KIND_DIGITS),
        ("KODE", 10, 2, tb.KIND_DIGITS),
        ("NIS", 10, 10, tb.KIND_DIGITS),
        ("TGL", 10, 2, tb.KIND_DIGITS),
        ("THN", 10, 2, tb.KIND_DIGITS),
    ]


def test_questions_numbered_down_each_column(blank, detected):
    _, layout, _, _ = blank
    _, blocks = detected
    mcq = [b for b in blocks if b.kind == tb.KIND_MCQ]
    assert sum(b.field_count for b in mcq) == layout.questions
    for b in mcq:
        assert b.values == list("ABCDE")
        # first bubble of the block sits on question `start`, option A
        ax, ay = layout.fields[f"q{b.start}"]["A"]
        assert abs(b.x0 + b.bw / 2 - ax * SCALE) < 3
        assert abs(b.y0 + b.bh / 2 - ay * SCALE) < 3


def test_detection_works_on_rotated_scan_of_blank():
    img, layout = synth.make_blank(seed=3)
    img = synth.distort(img, angle=0.4, dx=15, dy=-10, noise=4, jpeg=85)
    _, blocks = tb.detect_blocks(tb.prepare_sheet(img).page)
    assert sum(b.rows * b.cols for b in blocks) == sum(len(v) for v in layout.fields.values())


# ---------------------------------------------------------------------------
# Template content
# ---------------------------------------------------------------------------


def test_template_is_valid_for_omrchecker(tmp_path, blank, detected):
    _, layout, dims, page = blank
    blocks = label_like_user([*detected[1]], layout)
    template, problems = tb.build_template(blocks, dims)
    assert problems == []
    tb.save_template_folder(tmp_path, page, template)

    from src.template import Template
    from src.utils.parsing import open_config_with_defaults
    import gui

    gui.register_processors()
    config = open_config_with_defaults(tmp_path / "config.json")
    t = Template(tmp_path / "template.json", config)
    assert "NIS" in t.output_columns and "TglLahir" in t.output_columns
    assert [c for c in t.output_columns if c.startswith("q")] == [
        f"q{i}" for i in range(1, layout.questions + 1)
    ]
    assert template["customLabels"]["TglLahir"] == [
        "TglLahir_1..2", "TglLahir_3..4", "TglLahir_5..6"
    ]


def test_problems_reported():
    a = tb.Block(10, 10, 5, 5, 30, 30, 20, 20)
    b = tb.Block(300, 10, 5, 5, 30, 30, 20, 20)
    tb.set_kind(a, tb.KIND_MCQ)
    tb.set_kind(b, tb.KIND_MCQ)
    a.start = b.start = 1
    c = tb.Block(10, 300, 10, 3, 30, 30, 20, 20)
    tb.set_kind(c, tb.KIND_DIGITS)  # no group name
    _, problems = tb.build_template([a, b, c], [1000, 1400])
    text = " ".join(problems)
    assert "dobel" in text and "nama kolom" in text


def test_block_off_page_reported():
    a = tb.Block(900, 10, 5, 5, 30, 30, 20, 20)
    tb.set_kind(a, tb.KIND_MCQ)
    _, problems = tb.build_template([a], [1000, 1400])
    assert any("keluar dari halaman" in p for p in problems)


def test_manual_block_from_rect():
    b = tb.block_from_rect(100, 200, 100 + 4 * 36 + 30, 200 + 9 * 35 + 30, 10, 5, 30, 30)
    assert (b.rows, b.cols) == (10, 5)
    assert b.gap_x == pytest.approx(36)
    assert b.gap_y == pytest.approx(35)
    assert b.kind == tb.KIND_MCQ


def test_suggest_digits_for_ten_rows():
    b = tb.block_from_rect(0, 0, 3 * 33 + 30, 9 * 33 + 30, 10, 4, 30, 30)
    assert b.kind == tb.KIND_DIGITS and b.values == tb.DIGIT_VALUES and not b.horizontal


def test_suggest_month_block():
    b = tb.block_from_rect(0, 0, 30, 11 * 35 + 30, 12, 1, 30, 30)
    assert b.kind == tb.KIND_CUSTOM and b.values == tb.MONTH_VALUES and not b.horizontal


def test_parse_answer_key():
    answers, invalid = tb.parse_answer_key("1.a 2.B, c-d  e\nABX", "ABCDE")
    assert answers == list("ABCDEAB")
    assert invalid == ["X"]


def test_evaluation_trims_to_question_count():
    ev = tb.build_evaluation(["q1", "q2"], list("ABC"), correct=4, incorrect=-1)
    assert ev["options"]["answers_in_order"] == ["A", "B"]
    assert ev["marking_schemes"]["DEFAULT"] == {"correct": "4", "incorrect": "-1", "unmarked": "0"}


# ---------------------------------------------------------------------------
# End to end: blank -> template -> filled, distorted scans -> OMRChecker
# ---------------------------------------------------------------------------

SCANS = {
    # name: distortion as the sheet lands on the scanner glass
    "lurus.png": {},
    "geser.jpg": {"dx": 40, "dy": -30, "jpeg": 90},
    "miring.jpg": {"angle": 1.2, "dx": -25, "dy": 20, "noise": 5, "jpeg": 85},
    "miring_kecil.jpg": {"angle": -2.0, "scale": 0.98, "noise": 4, "jpeg": 80},
}


def test_end_to_end_reads_filled_sheets(tmp_path, blank, detected):
    img, layout, dims, page = blank
    blocks = label_like_user([*detected[1]], layout)
    template, problems = tb.build_template(blocks, dims)
    assert problems == []

    key = synth.random_responses(layout, seed=99, blank_rate=0)
    answers = [key[f"q{i}"] for i in range(1, layout.questions + 1)]
    evaluation = tb.build_evaluation(tb.question_labels(blocks), answers, correct=1)

    exam = tmp_path / "ujian"
    sheet = dataclasses.replace(page, source_name="ljk kosong.jpg")
    template, _ = tb.build_template(blocks, sheet)
    tb.save_template_folder(exam, sheet, template, evaluation)
    cv2.imencode(".jpg", img)[1].tofile(str(exam / "ljk kosong.jpg"))  # not graded

    expected = {}
    for k, (name, params) in enumerate(SCANS.items()):
        responses = synth.random_responses(layout, seed=k)
        sheet = synth.distort(synth.fill(img, layout, responses, seed=k), seed=k, **params)
        ok, buf = cv2.imencode(Path(name).suffix, sheet)
        buf.tofile(str(exam / name))
        row = synth.expected_row(layout, responses)
        row["score"] = sum(row[f"q{i}"] == answers[i - 1] for i in range(1, layout.questions + 1))
        expected[name] = row

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
    assert set(rows) == set(SCANS), "reference image must not be graded"

    mismatches = []
    for name, exp in expected.items():
        got = rows[name]
        for col, value in exp.items():
            g = got[col]
            if col == "score":
                if float(g) != value:
                    mismatches.append(f"{name} score: got {g}, expected {value}")
            elif g != value:
                mismatches.append(f"{name} {col}: got {g!r}, expected {value!r}")
    assert not mismatches, "\n".join(mismatches)


def test_saved_files(tmp_path, blank, detected):
    _, layout, dims, page = blank
    blocks = label_like_user([*detected[1]], layout)
    template, _ = tb.build_template(blocks, dims)
    written = tb.save_template_folder(tmp_path, page, template)
    assert set(written) == {"template.json", "config.json", tb.REFERENCE_FILENAME}
    config = json.loads((tmp_path / "config.json").read_text())
    assert config["dimensions"]["processing_width"] == dims[0]
    ref = cv2.imread(str(tmp_path / tb.REFERENCE_FILENAME), cv2.IMREAD_GRAYSCALE)
    assert ref.shape == (dims[1], dims[0])
