"""

 Template builder for OMRChecker

 Builds template.json (plus config.json, evaluation.json and an alignment
 reference image) from a scan of a blank answer sheet: bubbles are detected
 automatically and grouped into rectangular blocks, which the user then labels
 (questions, NIS, exam code, birth date ...) in the GUI.

 This module has no GUI dependency so it can be tested headlessly.

"""

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

DEFAULT_PAGE_WIDTH = 1240  # A4 at 150 DPI
MIN_BLOCK_BUBBLES = 4  # smaller groups are stray letters in headings
REFERENCE_FILENAME = "ljk_referensi.png"
ORIENTATION_FILENAME = "ljk_arah.png"  # tiny blank sheet: which way up a scan is

KIND_MCQ = "mcq"  # one question per row, options left to right
KIND_DIGITS = "digits"  # one digit per column, 0-9 top to bottom
KIND_CUSTOM = "custom"  # custom option values (e.g. months, letter codes)
KIND_IGNORE = "ignore"

DIGIT_VALUES = [str(i) for i in range(10)]
# Name columns: an empty bubble for a space, then A-Z
NAME_VALUES = [" "] + [chr(ord("A") + i) for i in range(26)]
MONTH_VALUES = [
    "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
    "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
]  # fmt: skip


def letters(n):
    return [chr(ord("A") + i) for i in range(n)]


@dataclass
class Bubble:
    cx: float
    cy: float
    w: float
    h: float
    extent: float = 0.785  # contour area / bounding box area (circle ~0.79)

    @property
    def x0(self):
        return self.cx - self.w / 2

    @property
    def y0(self):
        return self.cy - self.h / 2


@dataclass
class Block:
    """A rectangular grid of bubbles in page coordinates."""

    x0: float  # top-left corner of the first bubble
    y0: float
    rows: int
    cols: int
    gap_x: float  # distance between column centers
    gap_y: float  # distance between row centers
    bw: float
    bh: float
    kind: str = KIND_MCQ
    values: list = field(default_factory=list)
    # True: values run left to right, one field per row (MCQ).
    # False: values run top to bottom, one field per column (digits).
    horizontal: bool = True
    start: int = 1  # MCQ: number of the first question
    group: str = ""  # digits/custom: output column name, e.g. NIS
    section: str = ""  # MCQ: part of the test (numbering restarts per part)

    @property
    def x1(self):
        return self.x0 + self.gap_x * (self.cols - 1) + self.bw

    @property
    def y1(self):
        return self.y0 + self.gap_y * (self.rows - 1) + self.bh

    @property
    def field_count(self):
        return self.rows if self.horizontal else self.cols

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def describe(self):
        if self.kind == KIND_IGNORE:
            return f"Diabaikan ({self.rows}x{self.cols})"
        if self.kind == KIND_MCQ:
            end = self.start + self.field_count - 1
            part = f"Bagian {self.section}: " if self.section else ""
            return f"{part}Soal {self.start}-{end} ({self.values[0]}-{self.values[-1]})"
        name = self.group or "(belum diberi nama)"
        if self.kind == KIND_DIGITS:
            return f"{name}: {self.field_count} digit"
        first = "spasi" if self.values[0] == " " else self.values[0]
        return f"{name}: {self.field_count} isian ({first}, ..., {self.values[-1]})"

    def short_label(self):
        if self.kind == KIND_IGNORE:
            return "abaikan"
        if self.kind == KIND_MCQ:
            nums = f"{self.start}-{self.start + self.field_count - 1}"
            return f"{self.section}:{nums}" if self.section else nums
        return self.group or "?"


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------


def load_image(path):
    """Load a scan (image or first page of a PDF) as a BGR array."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(str(path)) as doc:
            page = doc[0]
            dpi = 150  # vector PDFs: 150 DPI is plenty
            widths = [i[2] for i in page.get_images(full=True)]
            if widths:  # a scanned page: keep the scan's own detail
                native = max(widths) / (page.rect.width / 72)
                dpi = int(min(300, max(150, native)))
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            if pix.n == 1:
                return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    data = np.fromfile(str(path), dtype=np.uint8)  # handles non-ASCII paths
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Gambar tidak bisa dibaca: {path}")
    return img


def page_dimensions_for(img, page_width=DEFAULT_PAGE_WIDTH):
    h, w = img.shape[:2]
    return [int(page_width), int(round(h * page_width / w))]


def to_page(img, page_dims):
    """Resize the whole image to the template page size, as OMRChecker does."""
    return cv2.resize(img, (int(page_dims[0]), int(page_dims[1])))


def ink_image(img):
    """Grayscale where any colored ink is dark (red LJK ink included)."""
    if img.ndim == 2:
        return img
    return img.min(axis=2)


# ---------------------------------------------------------------------------
# Sheet alignment: corner markers (preferred) or feature matching
# ---------------------------------------------------------------------------


@dataclass
class Sheet:
    """A blank sheet prepared the way OMRChecker will see each scan."""

    page: np.ndarray  # BGR image in template page coordinates
    page_dims: list  # [width, height]; also the processing size
    markers: list = None  # corner marker centres [[x, y] x4], if the sheet has them
    marker_size: float = 0
    source_name: str = ""  # file the template was made from
    source_blank: bool = True  # False when that sheet was filled in (then it is graded)
    detail: np.ndarray = None  # same page at higher resolution, for finding faint bubbles

    @property
    def uses_markers(self):
        return bool(self.markers)

    def preprocessors(self):
        if self.uses_markers:
            options = {
                "markerCenters": [[round(x, 1), round(y, 1)] for x, y in self.markers],
                "markerSize": round(self.marker_size, 1),
                "orientationReference": ORIENTATION_FILENAME,
            }
            name = "AlignOnMarkers"
        else:
            options = {"reference": REFERENCE_FILENAME, "maxFeatures": 2000, "2d": True}
            name = "FeatureBasedAlignment"
        if self.source_name and self.source_blank:
            # a blank sheet copied next to the scans is not a student's sheet
            options["excludeFiles"] = [self.source_name]
        return [{"name": name, "options": options}]


def _corner_markers(gray):
    import src.processors.manager  # noqa: F401  (must load before any processor)
    from src.processors.AlignOnMarkers import find_corner_markers, marker_centers

    rects = find_corner_markers(gray)
    if not rects:
        return None, 0
    return marker_centers(rects), float(np.median([max(r[2], r[3]) for r in rects]))


def prepare_sheet(img, page_width=DEFAULT_PAGE_WIDTH, source_name=""):
    """Resize the blank scan the way OMRChecker does. When the sheet has four
    solid corner squares, also straighten it on them: every student scan is
    later mapped onto these same marker positions (AlignOnMarkers).

    A higher resolution copy (up to 2x) is kept for bubble detection: thin,
    faint bubble outlines often vanish at template size."""
    dims = page_dimensions_for(img, page_width)
    scan = to_page(img, dims)
    k = min(img.shape[1] / dims[0], 2.0)
    detail_dims = [int(round(dims[0] * k)), int(round(dims[1] * k))]
    detail_scan = to_page(img, detail_dims) if k > 1.25 else None

    found, size = _corner_markers(cv2.cvtColor(scan, cv2.COLOR_BGR2GRAY))
    if found is None:
        return Sheet(scan, list(dims), source_name=source_name, detail=detail_scan)
    tl, tr, bl, br = found
    # Axis-aligned target rectangle so the blank (and the template) is straight
    left, right = (tl[0] + bl[0]) / 2, (tr[0] + br[0]) / 2
    top, bottom = (tl[1] + tr[1]) / 2, (bl[1] + br[1]) / 2
    target = np.array([[left, top], [right, top], [left, bottom], [right, bottom]], np.float32)
    matrix = cv2.getPerspectiveTransform(found, target)
    page = cv2.warpPerspective(scan, matrix, tuple(dims), borderValue=(255, 255, 255))
    detail = None
    if detail_scan is not None:
        zoom = np.diag([k, k, 1.0])
        detail = cv2.warpPerspective(
            detail_scan, zoom @ matrix @ np.linalg.inv(zoom), tuple(detail_dims),
            borderValue=(255, 255, 255),
        )
    return Sheet(
        page, list(dims), markers=target.tolist(), marker_size=size,
        source_name=source_name, detail=detail,
    )


# ---------------------------------------------------------------------------
# Bubble detection
# ---------------------------------------------------------------------------


def _remove_lines(binary, width):
    """Erase box borders and separator lines so bubbles touching them stay
    separate shapes; then close the small gaps this leaves in the rings."""
    length = max(25, width // 25)  # longer than any bubble
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1))
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length))
    )
    lines = cv2.dilate(horizontal | vertical, np.ones((3, 3), np.uint8))
    cleaned = cv2.bitwise_and(binary, cv2.bitwise_not(lines))
    return cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def detect_bubbles(page_img, min_frac=0.007, max_frac=0.05, with_extra=False):
    """Find bubble outlines on a blank sheet already resized to page size."""
    gray = ink_image(page_img)
    width = gray.shape[1]
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    block = max(15, (width // 40) | 1)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 8
    )
    min_size, max_size = width * min_frac, width * max_frac
    candidates = []
    for img in (binary, _remove_lines(binary, width)):
        contours, _ = cv2.findContours(img, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if not (min_size <= w <= max_size and min_size <= h <= max_size):
                continue
            if not 0.5 <= w / h <= 2.0:
                continue
            area = cv2.contourArea(c)
            hull_area = cv2.contourArea(cv2.convexHull(c))
            if hull_area <= 0 or area / hull_area < 0.9:
                continue
            extent = area / (w * h)
            if not 0.55 <= extent <= 1.0:
                continue
            candidates.append((x, y, w, h, extent))

    # Outer outline wins over the inner edge of the ring and letters inside
    # it; the same bubble found in both passes is kept once.
    candidates.sort(key=lambda r: r[2] * r[3], reverse=True)
    kept = []
    for x, y, w, h, extent in candidates:
        cx, cy = x + w / 2, y + h / 2
        if any(kx <= cx <= kx + kw and ky <= cy <= ky + kh for kx, ky, kw, kh, _ in kept):
            continue
        kept.append((x, y, w, h, extent))

    every = [Bubble(x + w / 2, y + h / 2, w, h, e) for x, y, w, h, e in kept]
    bubbles = _dominant_shape(every)
    main = bubbles + _find_by_example(ink_image(page_img), bubbles)
    if not with_extra:
        return main
    return main, _other_sizes(ink_image(page_img), every, main)


def _other_sizes(gray, candidates, main):
    """Groups of round bubbles of another size than the main ones (e.g. big
    unlettered circles for gender or booklet code). Each group is a list of
    at least 2 alike, truly ring-shaped bubbles."""
    if not main:
        return []
    size = float(np.median([max(b.w, b.h) for b in main]))
    taken = np.array([[b.cx, b.cy] for b in main])
    gray_f = gray.astype(np.float32)
    pool = []
    for b in candidates:
        if np.min(np.hypot(taken[:, 0] - b.cx, taken[:, 1] - b.cy)) < 0.5 * size:
            continue
        if not (0.8 <= b.w / b.h <= 1.25 and 0.5 * size <= max(b.w, b.h) <= 2.5 * size):
            continue
        if _ring_score(gray_f, b.cx, b.cy, (b.w + b.h) / 4 - 1) < 0.85:
            continue
        pool.append(b)
    groups = []
    while pool:
        seed = pool.pop(0)
        alike = [b for b in pool if abs(b.w - seed.w) <= 0.2 * seed.w and abs(b.h - seed.h) <= 0.2 * seed.h]
        if alike:
            groups.append([seed] + alike)
            pool = [b for b in pool if b not in alike]
    return groups


def _ring_score(gray, cx, cy, r):
    """Share of points on a circle of radius ~r darker than just outside it:
    ~1 for a bubble outline (however faint), low for digits and letters."""
    angles = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    cos, sin = np.cos(angles), np.sin(angles)
    gap = max(3.0, r * 0.33)
    h, w = gray.shape
    best = 0.0
    for rr in (r - 1.5, r - 0.5, r + 0.5):
        xs, ys = (cx + rr * cos).astype(int), (cy + rr * sin).astype(int)
        xo, yo = (cx + (rr + gap) * cos).astype(int), (cy + (rr + gap) * sin).astype(int)
        if min(xs.min(), xo.min(), ys.min(), yo.min()) < 0 or max(xs.max(), xo.max()) >= w or max(ys.max(), yo.max()) >= h:
            return 0.0
        best = max(best, float(np.mean(gray[ys, xs] < gray[yo, xo] - 6)))
    return best


def _find_by_example(gray, bubbles, threshold=0.45, ring_min=0.7):
    """Find bubbles the outline pass missed (faint print, broken outlines) by
    matching the average look of the bubbles already found (normalized
    cross-correlation ignores contrast), then keeping only true rings."""
    if len(bubbles) < 8:
        return []
    bw = float(np.median([b.w for b in bubbles]))
    bh = float(np.median([b.h for b in bubbles]))
    m = max(3, int(round(bw * 0.12)))
    pw, ph = int(round(bw)) + 2 * m, int(round(bh)) + 2 * m
    paper = float(np.median(gray))
    patches = []
    for b in bubbles:
        x0, y0 = int(round(b.cx - pw / 2)), int(round(b.cy - ph / 2))
        p = gray[y0 : y0 + ph, x0 : x0 + pw]
        inner = p[m + 2 : -m - 2, m + 2 : -m - 2] if p.shape == (ph, pw) else None
        if inner is not None and inner.size and inner.mean() > paper - 60:  # not filled in
            patches.append(p.astype(np.float32))
    if len(patches) < 5:
        return []
    example = np.mean(patches, axis=0).astype(np.uint8)
    res = cv2.matchTemplate(gray, example, cv2.TM_CCOEFF_NORMED)
    k = max(3, int(min(bw, bh) * 0.7))
    peaks = np.argwhere((res >= threshold) & (res == cv2.dilate(res, np.ones((k, k), np.uint8))))
    if not len(peaks):
        return []
    known = np.array([[b.cx, b.cy] for b in bubbles])
    r = (bw + bh) / 4
    extent = float(np.median([b.extent for b in bubbles]))
    gray_f = gray.astype(np.float32)
    found = []
    for y, x in peaks:
        cx, cy = x + pw / 2, y + ph / 2
        if np.min(np.hypot(known[:, 0] - cx, known[:, 1] - cy)) < 0.5 * bw:
            continue
        if _ring_score(gray_f, cx, cy, r) >= ring_min:
            found.append(Bubble(cx, cy, bw, bh, extent))
    return found


def _dominant_shape(bubbles, size_tol=0.2, extent_tol=0.08):
    """Keep shapes like the most common one: same width, height and roundness.

    Drops text, logos and write-in boxes, which are rarer than bubbles and
    differ in size, are narrow (digits like 6, 8, 0) or are square (extent
    ~1.0) where bubbles are round."""
    if not bubbles:
        return []
    ws = np.array([b.w for b in bubbles], dtype=float)
    hs = np.array([b.h for b in bubbles], dtype=float)
    extents = np.array([b.extent for b in bubbles])

    def similar(i):
        return (
            (np.abs(ws - ws[i]) <= ws[i] * size_tol)
            & (np.abs(hs - hs[i]) <= hs[i] * size_tol)
            & (np.abs(extents - extents[i]) <= extent_tol)
        )

    best = max(range(len(bubbles)), key=lambda i: np.count_nonzero(similar(i)))
    mask = similar(best)
    return [b for b, keep in zip(bubbles, mask) if keep]


# ---------------------------------------------------------------------------
# Grouping into blocks
# ---------------------------------------------------------------------------


def _cluster_1d(values, tol):
    """Group sorted 1-D coordinates; returns cluster centers and labels."""
    order = np.argsort(values)
    labels = np.empty(len(values), dtype=int)
    centers, current = [], [values[order[0]]]
    labels[order[0]] = 0
    for idx in order[1:]:
        v = values[idx]
        if v - np.mean(current) > tol:
            centers.append(float(np.mean(current)))
            current = []
        current.append(v)
        labels[idx] = len(centers)
    centers.append(float(np.mean(current)))
    return centers, labels


def _typical_pitch(distances):
    """Median distance to the nearest neighbour along one axis."""
    nearest = distances.min(axis=1)
    nearest = nearest[np.isfinite(nearest)]
    return float(np.median(nearest)) if len(nearest) else 0.0


def group_bubbles(bubbles, link_factor=2.8, pitch_factor=1.8):
    """Split bubbles into connected groups of row/column neighbours."""
    if not bubbles:
        return []
    cx = np.array([b.cx for b in bubbles])
    cy = np.array([b.cy for b in bubbles])
    bw = float(np.median([b.w for b in bubbles]))
    bh = float(np.median([b.h for b in bubbles]))
    dx = np.abs(cx[:, None] - cx[None, :])
    dy = np.abs(cy[:, None] - cy[None, :])
    in_row = dy < 0.45 * bh
    in_col = dx < 0.45 * bw
    # Link only neighbours at about the usual bubble pitch, so blocks printed
    # close together (name box next to the number box) stay apart.
    pitch_x = _typical_pitch(np.where(in_row & (dx > 0), dx, np.inf))
    pitch_y = _typical_pitch(np.where(in_col & (dy > 0), dy, np.inf))
    max_dx = min(link_factor * bw, pitch_factor * pitch_x) if pitch_x else link_factor * bw
    max_dy = min(link_factor * bh, pitch_factor * pitch_y) if pitch_y else link_factor * bh
    adj = (in_row & (dx < max_dx)) | (in_col & (dy < max_dy))

    parent = list(range(len(bubbles)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(*np.nonzero(np.triu(adj, 1))):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    groups = {}
    for i in range(len(bubbles)):
        groups.setdefault(find(i), []).append(bubbles[i])
    return [g for g in groups.values() if len(g) >= MIN_BLOCK_BUBBLES or _neat_small_group(g)]


def _neat_small_group(group):
    """2-3 bubbles in one straight row or column at a bubble-like spacing
    (gender L/P, booklet X/Y). Stray letters in headings rarely line up so."""
    if not 2 <= len(group) <= 3:
        return False
    size = float(np.median([max(b.w, b.h) for b in group]))
    xs = np.array([b.cx for b in group])
    ys = np.array([b.cy for b in group])
    if np.ptp(xs) < 0.3 * size:
        steps = np.diff(np.sort(ys))
    elif np.ptp(ys) < 0.3 * size:
        steps = np.diff(np.sort(xs))
    else:
        return False
    return bool(np.all((steps >= 1.1 * size) & (steps <= 2.0 * size)))


def _split_points(centers, factor=1.25):
    """Indexes where the spacing jumps (e.g. questions grouped by five)."""
    if len(centers) < 3:
        return []
    diffs = np.diff(centers)
    base = float(np.median(diffs))
    return [i + 1 for i, d in enumerate(diffs) if d > base * factor]


def _keep_full_lines(centers, line_of, counts_other, min_share=0.4):
    """Drop rows/columns holding few bubbles: strays inside a block. A short
    column of 2+ bubbles is real (e.g. a month's first digit: only 0-1)."""
    counts = np.bincount(line_of, minlength=len(centers))
    return {i for i, n in enumerate(counts) if n >= min(2, min_share * counts.max())}


def _fit_grid(values, line_of, centers, default_step):
    """(first centre, step) of evenly spaced lines fitted to all bubbles."""
    if len(centers) < 2:
        return centers[0], default_step
    step, first = np.polyfit(np.asarray(line_of, dtype=float), np.asarray(values, dtype=float), 1)
    return float(first), float(step)


def block_from_bubbles(bubbles):
    """Fit regular grid blocks to a group of bubbles.

    Returns a list because irregular spacing splits the group into several
    evenly spaced blocks (answer columns, questions grouped by five)."""
    bw = float(np.median([b.w for b in bubbles]))
    bh = float(np.median([b.h for b in bubbles]))
    xs = np.array([b.cx for b in bubbles])
    ys = np.array([b.cy for b in bubbles])
    col_centers, col_of = _cluster_1d(xs, bw * 0.5)
    row_centers, row_of = _cluster_1d(ys, bh * 0.5)

    # Split at wider gaps first (separate boxes linked by a narrow margin,
    # questions grouped by five), then clean each part on its own
    col_cuts = [0] + _split_points(col_centers) + [len(col_centers)]
    row_cuts = [0] + _split_points(row_centers) + [len(row_centers)]
    if len(col_cuts) == 2 and len(row_cuts) == 2:
        good_cols = _keep_full_lines(col_centers, col_of, len(row_centers))
        good_rows = _keep_full_lines(row_centers, row_of, len(col_centers))
        if len(good_cols) < len(col_centers) or len(good_rows) < len(row_centers):
            kept = [b for b, c, r in zip(bubbles, col_of, row_of) if c in good_cols and r in good_rows]
            return block_from_bubbles(kept) if len(kept) >= MIN_BLOCK_BUBBLES else []
    if len(col_cuts) > 2 or len(row_cuts) > 2:
        blocks = []
        for c0, c1 in zip(col_cuts, col_cuts[1:]):
            for r0, r1 in zip(row_cuts, row_cuts[1:]):
                part = [
                    b
                    for b, ci, ri in zip(bubbles, col_of, row_of)
                    if c0 <= ci < c1 and r0 <= ri < r1
                ]
                if len(part) >= MIN_BLOCK_BUBBLES:
                    blocks.extend(block_from_bubbles(part))
        return blocks

    cols, rows = len(col_centers), len(row_centers)
    # Straight-line fit through every bubble: a median step rounded to whole
    # pixels drifts across a wide block (0.2 px x 20 columns = 4 px off)
    first_x, gap_x = _fit_grid(xs, col_of, col_centers, bw * 2)
    first_y, gap_y = _fit_grid(ys, row_of, row_centers, bh * 2)
    block = Block(
        x0=first_x - bw / 2,
        y0=first_y - bh / 2,
        rows=rows,
        cols=cols,
        gap_x=gap_x,
        gap_y=gap_y,
        bw=bw,
        bh=bh,
    )
    suggest_kind(block)
    return [block]


def block_from_rect(x0, y0, x1, y1, rows, cols, bw, bh):
    """Manual block: evenly spaced grid filling a rectangle drawn by the user."""
    gap_x = (x1 - x0 - bw) / (cols - 1) if cols > 1 else bw * 2
    gap_y = (y1 - y0 - bh) / (rows - 1) if rows > 1 else bh * 2
    block = Block(x0, y0, rows, cols, gap_x, gap_y, bw, bh)
    suggest_kind(block)
    return block


def suggest_kind(block):
    """Guess what a block is from its shape; the user confirms in the GUI."""
    # 10 rows x 5 columns is ambiguous (10 questions A-E or a 5-digit
    # number); 10 questions is far more common on answer sheets.
    if block.cols == 5 or (block.cols in (2, 3, 4) and block.rows != 10):
        set_kind(block, KIND_MCQ)
    elif block.rows == 10:
        set_kind(block, KIND_DIGITS)
    elif block.rows == 12 and block.cols <= 2:
        set_kind(block, KIND_CUSTOM, MONTH_VALUES, horizontal=False)
    elif block.rows in (26, 27) and block.cols >= 5:  # name: (space) A-Z
        values = NAME_VALUES if block.rows == 27 else NAME_VALUES[1:]
        set_kind(block, KIND_CUSTOM, values, horizontal=False)
    else:
        down = block.cols == 1  # a single column: options run down the page
        set_kind(block, KIND_CUSTOM, letters(block.rows if down else block.cols), horizontal=not down)
    block.group = suggest_group(block)
    return block


def suggest_group(block):
    """Likely output column name; empty when it cannot be guessed."""
    if block.kind == KIND_CUSTOM and block.values[-1:] == ["Z"]:
        return "Nama"
    if block.kind == KIND_DIGITS:
        if block.cols == 6:
            return "TglLahir"
        if block.cols in (3, 4):
            return "KodeSoal"
        if block.cols >= 7:
            return "NIS"
    return ""


def set_kind(block, kind, values=None, horizontal=None):
    block.kind = kind
    if kind == KIND_MCQ:
        # one column of options (e.g. TYPE A-D down the page) = one question
        block.horizontal = not (block.cols == 1 and block.rows > 1)
        block.values = values or letters(block.cols if block.horizontal else block.rows)
    elif kind == KIND_DIGITS:
        block.horizontal = False
        block.values = values or DIGIT_VALUES[: block.rows]
    elif kind == KIND_CUSTOM:
        block.horizontal = horizontal if horizontal is not None else block.horizontal
        block.values = values or letters(block.cols if block.horizontal else block.rows)
    return block


def _majority_questions(blocks, min_count=6):
    """A block shape repeated many times is a column of questions, even when
    it looks like a number field (e.g. 10 questions with options A/B)."""
    shapes = {}
    for b in blocks:
        shapes.setdefault((b.rows, b.cols), []).append(b)
    for (rows, cols), same in shapes.items():
        if len(same) >= min_count and cols <= 5:
            for b in same:
                if b.kind != KIND_MCQ:
                    set_kind(b, KIND_MCQ)
                    b.group = ""


def _tidy_suggestions(blocks):
    """Second look once parts are known. Returns True if anything changed."""
    sections = {}
    for b in blocks:
        if b.kind == KIND_MCQ:
            sections.setdefault(b.section, []).append(b)
    several = len(sections) > 1 or sum(len(v) for v in sections.values()) > 1
    changed = False
    for b in blocks:
        alone = b.kind == KIND_MCQ and several and len(sections.get(b.section, [])) == 1
        # same shape as questions elsewhere (e.g. a separate 10 x A/B part): questions
        twin = any(o is not b and o.kind == KIND_MCQ and (o.rows, o.cols) == (b.rows, b.cols) for o in blocks)
        if alone and b.horizontal and b.rows == 10 and not twin:
            set_kind(b, KIND_DIGITS)  # a lone 10-row grid: a code or number
            b.group = suggest_group(b)
            changed = True
        elif alone and b.horizontal and b.rows <= 3:
            set_kind(b, KIND_IGNORE)  # "how to fill in" examples, legends
            changed = True
        elif b.kind == KIND_CUSTOM and b.cols == 1 and 3 <= b.rows <= 5:
            set_kind(b, KIND_MCQ)  # one question with options down the page
            b.group = ""
            changed = True
    return changed


def detect_blocks(source):
    """Bubbles and blocks in template page coordinates. `source` is a Sheet
    (its high resolution copy is searched when there is one) or an image."""
    img, k = source, 1.0
    if isinstance(source, Sheet):
        img = source.detail if source.detail is not None else source.page
        k = img.shape[1] / source.page_dims[0]

    def scale(bs):
        return [Bubble(b.cx / k, b.cy / k, b.w / k, b.h / k, b.extent) for b in bs]

    main, extra = detect_bubbles(img, with_extra=True)
    bubbles = scale(main)
    extra_groups = [scale(g) for g in extra]
    blocks = []
    small = []  # 2-3 bubble blocks: kept only when standing apart (see below)
    for group in group_bubbles(bubbles):
        (small if len(group) < MIN_BLOCK_BUBBLES else blocks).extend(block_from_bubbles(group))
    main_blocks = list(blocks)

    def inside_a_block(b):  # pencil marks in a filled sheet look like other sizes
        return any(
            m.x0 - m.gap_x / 2 <= b.cx <= m.x1 + m.gap_x / 2 and m.y0 - m.gap_y / 2 <= b.cy <= m.y1 + m.gap_y / 2
            for m in main_blocks
        )

    def beside_a_block(b):
        """Lined up with the rows (or columns) of a big block right next to it:
        question numbers or pencil marks, not a field of its own. Gender L/P
        or booklet X/Y sit in their own box, not in line with another grid."""
        def on_grid(values, own_step, start, step, count):
            # labels of a grid's rows share its spacing and sit exactly in line
            if len(values) > 1 and abs(own_step - step) > 0.15 * step:
                return False
            return all(
                abs((v - start) / step - round((v - start) / step)) * step < 0.15 * step
                and -0.5 <= (v - start) / step <= count - 0.5
                for v in values
            )

        ys = [b.y0 + b.bh / 2 + i * b.gap_y for i in range(b.rows)]
        xs = [b.x0 + b.bw / 2 + j * b.gap_x for j in range(b.cols)]
        for m in main_blocks:
            gap_x = max(m.x0 - b.x1, b.x0 - m.x1)
            gap_y = max(m.y0 - b.y1, b.y0 - m.y1)
            if gap_x < 2.5 * m.gap_x and on_grid(ys, b.gap_y, m.y0 + m.bh / 2, m.gap_y, m.rows):
                return True
            if gap_y < 2.5 * m.gap_y and on_grid(xs, b.gap_x, m.x0 + m.bw / 2, m.gap_x, m.cols):
                return True
        return False

    for same_size in extra_groups:  # other bubble sizes, grouped on their own
        same_size = [b for b in same_size if not inside_a_block(b)]
        for group in group_bubbles(same_size):
            for b in block_from_bubbles(group):
                if not beside_a_block(b):
                    (small if len(group) < MIN_BLOCK_BUBBLES else blocks).append(b)
        bubbles = bubbles + same_size

    def apart(b):
        return not beside_a_block(b)

    blocks += [b for b in small if apart(b)]
    _majority_questions(blocks)
    page = source.page if isinstance(source, Sheet) else source
    assign_sections(blocks, page)
    if _tidy_suggestions(blocks):
        assign_sections(blocks, page)
    return bubbles, sort_blocks(blocks)


def section_order(section):
    return (ROMAN.index(section), "") if section in ROMAN else (len(ROMAN), section)


def sort_blocks(blocks):
    """Identity blocks top to bottom, then questions in number order."""
    return sorted(
        blocks,
        key=lambda b: (1, section_order(b.section), b.start) if b.kind == KIND_MCQ
        else (0, round(b.y0 / 20), b.x0),
    )


def number_mcq_blocks(blocks, first=1):
    """Number questions down each column of blocks, then left to right;
    each part (section) of the test starts again at `first`."""
    sections = {}
    for b in blocks:
        if b.kind == KIND_MCQ:
            sections.setdefault(b.section, []).append(b)
    for mcq in sections.values():
        bw = float(np.median([b.bw for b in mcq]))
        _, col_of = _cluster_1d(np.array([b.x0 for b in mcq]), bw * 2)
        order = sorted(range(len(mcq)), key=lambda i: (col_of[i], mcq[i].y0))
        n = first
        for i in order:
            mcq[i].start = n
            n += mcq[i].field_count


ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _horizontal_lines(page_img):
    """Mask of long horizontal printed lines (box borders)."""
    gray = ink_image(page_img)
    width = gray.shape[1]
    binary = cv2.adaptiveThreshold(
        cv2.GaussianBlur(gray, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV, max(15, (width // 40) | 1), 8,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, width // 25), 1))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _line_between(lines, upper, lower):
    """A printed line runs between two blocks stacked one above the other."""
    x0, x1 = int(max(upper.x0, lower.x0)), int(min(upper.x1, lower.x1))
    y0, y1 = int(upper.y1) + 1, int(lower.y0) - 1
    if x1 - x0 < 5 or y1 <= y0:
        return False
    band = lines[y0:y1, x0:x1] > 0
    return bool(band.size) and bool((band.mean(axis=1) > 0.6).any())


def assign_sections(blocks, page_img=None):
    """Group question blocks into the test's parts (I, II, III, ...).

    Blocks belong to one part when they have the same options and either sit
    side by side with aligned tops or continue the same column below, with no
    printed box border between them. One part only: no section names."""
    mcq = [b for b in blocks if b.kind == KIND_MCQ]
    if not mcq:
        return blocks
    lines = _horizontal_lines(page_img) if page_img is not None else None
    parent = list(range(len(mcq)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(mcq):
        for j in range(i + 1, len(mcq)):
            b = mcq[j]
            if a.values != b.values or a.horizontal != b.horizontal:
                continue
            pitch_y = max(a.gap_y, b.gap_y)
            side_by_side = abs(a.y0 - b.y0) < pitch_y and min(abs(a.x0 - b.x1), abs(b.x0 - a.x1)) < 6 * max(a.gap_x, b.gap_x)
            upper, lower = (a, b) if a.y0 < b.y0 else (b, a)
            stacked = abs(a.x0 - b.x0) < max(a.gap_x, b.gap_x) and 0 < lower.y0 - upper.y1 < 3 * pitch_y
            if stacked and lines is not None and _line_between(lines, upper, lower):
                stacked = False
            if side_by_side or stacked:
                parent[find(i)] = find(j)

    groups = {}
    for i, b in enumerate(mcq):
        groups.setdefault(find(i), []).append(b)
    if len(groups) == 1:
        for b in mcq:
            b.section = ""
    else:
        ordered = sorted(groups.values(), key=lambda g: (round(min(b.y0 for b in g) / 40), min(b.x0 for b in g)))
        for k, g in enumerate(ordered):
            for b in g:
                b.section = ROMAN[k] if k < len(ROMAN) else f"Bagian{k + 1}"
    number_mcq_blocks(blocks)
    return blocks


def split_block(block, by="column", bubbles=None):
    """Cut a block into single columns (or rows), e.g. a seat-code block whose
    columns hold different letters (A-J, K-T, U-Z). With the detected
    `bubbles`, each part is refitted to the bubbles really printed there
    (a U-Z column has 6, not 10)."""
    parts = []
    n = block.cols if by == "column" else block.rows
    for i in range(n):
        if by == "column":
            b = Block(block.x0 + i * block.gap_x, block.y0, block.rows, 1,
                      block.gap_x, block.gap_y, block.bw, block.bh)  # fmt: skip
        else:
            b = Block(block.x0, block.y0 + i * block.gap_y, 1, block.cols,
                      block.gap_x, block.gap_y, block.bw, block.bh)  # fmt: skip
        if bubbles:
            inside = [x for x in bubbles if b.x0 - 2 <= x.cx <= b.x1 + 2 and b.y0 - 2 <= x.cy <= b.y1 + 2]
            fitted = block_from_bubbles(inside) if len(inside) >= 2 else []
            if len(fitted) == 1:
                b = fitted[0]
        suggest_kind(b)
        if block.kind in (KIND_DIGITS, KIND_CUSTOM) and block.group:
            b.group = block.group
            if by == "column" and not block.horizontal and b.rows == block.rows:
                set_kind(b, block.kind, list(block.values), horizontal=False)
        parts.append(b)
    return parts


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------


def _label_prefix(group):
    clean = re.sub(r"[^A-Za-z_]", "", group.replace(" ", "_"))
    return clean or "Kolom"


def section_prefix(section):
    """Field label prefix of a part: q1, q2 ... or I_1, II_1, Motivasi_1 ...
    (OMRChecker labels cannot have digits in the prefix)."""
    if not section.strip():
        return "q"
    text = re.sub(r"\d+", lambda m: ROMAN[int(m.group()) - 1] if 0 < int(m.group()) <= len(ROMAN) else "X", section)
    return re.sub(r"[^A-Za-z_]", "", text.replace(" ", "_")) + "_"


def sections_of(blocks):
    """{label prefix: display name} of the question parts, in order."""
    out = {}
    for b in sorted((b for b in blocks if b.kind == KIND_MCQ), key=lambda b: section_order(b.section)):
        out.setdefault(section_prefix(b.section), b.section)
    return out


def count_marked(page_img, blocks):
    """Bubbles that look pencilled in (much darker inside than the paper)."""
    gray = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY) if page_img.ndim == 3 else page_img
    paper = float(np.median(gray))
    marked = 0
    for b in blocks:
        r = max(2, int(min(b.bw, b.bh) * 0.25))
        for i in range(b.rows):
            for j in range(b.cols):
                cx = int(b.x0 + j * b.gap_x + b.bw / 2)
                cy = int(b.y0 + i * b.gap_y + b.bh / 2)
                patch = gray[max(0, cy - r) : cy + r + 1, max(0, cx - r) : cx + r + 1]
                if patch.size and patch.mean() < paper * 0.55:
                    marked += 1
    return marked


def build_template(blocks, sheet):
    """Return (template dict, list of problems).

    `sheet` is a Sheet, or just [width, height] for a sheet without markers."""
    if not isinstance(sheet, Sheet):
        sheet = Sheet(None, list(sheet))
    page_dims = sheet.page_dims
    problems = []
    active = [b for b in blocks if b.kind != KIND_IGNORE]
    if not active:
        problems.append("Belum ada blok yang dipakai.")

    field_blocks, custom_labels, used = {}, {}, set()

    mcq = sorted((b for b in active if b.kind == KIND_MCQ), key=lambda b: (section_order(b.section), b.start))
    prefixes = {}
    for b in mcq:
        prefix = section_prefix(b.section)
        if prefixes.setdefault(prefix, b.section) != b.section:
            problems.append(f"Nama bagian '{b.section}' dan '{prefixes[prefix]}' terlalu mirip.")
        labels = [f"{prefix}{b.start + i}" for i in range(b.field_count)]
        clash = used.intersection(labels)
        if clash:
            part = f"bagian {b.section}: " if b.section else ""
            nums = sorted(int(c[len(prefix):]) for c in clash)
            problems.append(f"Nomor soal dobel ({part}{', '.join(map(str, nums))})")
        used.update(labels)
        end = b.start + b.field_count - 1
        name = f"Soal_{prefix}{b.start}_{end}" if b.section else f"Soal_{b.start}_{end}"
        field_blocks[name] = _field_block(
            b, [f"{prefix}{b.start}..{end}"] if end > b.start else [f"{prefix}{b.start}"]
        )

    others = [b for b in active if b.kind != KIND_MCQ]
    groups = {}
    for b in others:
        if not b.group.strip():
            problems.append(f"Blok di ({int(b.x0)}, {int(b.y0)}) belum diberi nama kolom.")
            continue
        groups.setdefault(b.group.strip(), []).append(b)
    for name, members in groups.items():
        prefix = _label_prefix(name) + "_"
        if name in used or re.fullmatch(r"[A-Za-z_]+_?\d+", name) and name.rstrip("0123456789") in prefixes:
            problems.append(f"Nama kolom '{name}' bentrok dengan nama soal.")
        members.sort(key=lambda b: (b.x0, b.y0) if not b.horizontal else (b.y0, b.x0))
        n, strings = 1, []
        for k, b in enumerate(members, 1):
            end = n + b.field_count - 1
            label = f"{prefix}{n}..{end}" if end > n else f"{prefix}{n}"
            strings.append(label)
            block_name = prefix[:-1] if len(members) == 1 else f"{prefix}blok{k}"
            field_blocks[block_name] = _field_block(b, [label])
            n = end + 1
        custom_labels[name] = strings

    for b in active:
        if b.x0 < 0 or b.y0 < 0 or b.x1 >= page_dims[0] or b.y1 >= page_dims[1]:
            problems.append(f"Blok di ({int(b.x0)}, {int(b.y0)}) keluar dari halaman.")
        if len(b.values) != (b.cols if b.horizontal else b.rows):
            problems.append(
                f"Blok di ({int(b.x0)}, {int(b.y0)}): jumlah pilihan ({len(b.values)}) "
                f"tidak sama dengan jumlah bulatan ({b.cols if b.horizontal else b.rows})."
            )

    bubble = [
        int(round(float(np.median([b.bw for b in active])))) if active else 20,
        int(round(float(np.median([b.bh for b in active])))) if active else 20,
    ]
    if sheet.page is not None and sheet.source_name:
        sheet.source_blank = count_marked(sheet.page, active) < 3
    template = {
        "pageDimensions": [int(page_dims[0]), int(page_dims[1])],
        "bubbleDimensions": bubble,
        "preProcessors": sheet.preprocessors(),
        "fieldBlocks": field_blocks,
    }
    if custom_labels:
        template["customLabels"] = custom_labels
    return template, problems


def _field_block(b, field_labels):
    return {
        "origin": [int(round(b.x0)), int(round(b.y0))],
        "bubbleDimensions": [int(round(b.bw)), int(round(b.bh))],
        "bubbleValues": list(b.values),
        "direction": "horizontal" if b.horizontal else "vertical",
        "bubblesGap": round(b.gap_x if b.horizontal else b.gap_y, 2),
        "labelsGap": round(b.gap_y if b.horizontal else b.gap_x, 2),
        "fieldLabels": field_labels,
    }


def build_config(processing_dims):
    w, h = int(processing_dims[0]), int(processing_dims[1])
    return {
        # Process at template resolution: no detail lost to the default 666px
        "dimensions": {
            "processing_width": w,
            "processing_height": h,
            "display_width": w,
            "display_height": h,
        },
        "pdf_params": {"pdf_page": "1-"},
        "outputs": {"show_image_level": 0},
    }


def question_labels(blocks):
    """Question labels in order: by part, then number."""
    labels = []
    mcq = sorted((b for b in blocks if b.kind == KIND_MCQ), key=lambda b: (section_order(b.section), b.start))
    for b in mcq:
        prefix = section_prefix(b.section)
        labels.extend(f"{prefix}{b.start + i}" for i in range(b.field_count))
    return labels


def parse_answer_key(text, allowed):
    """'ABCDE abcde 1.A 2-B' -> ['A','B',...]; ignores spaces, digits, punctuation."""
    allowed = {a.upper() for a in allowed}
    answers, invalid = [], []
    for ch in text.upper():
        if ch.isspace() or ch.isdigit() or ch in ".,;:-_()/":
            continue
        if ch in allowed:
            answers.append(ch)
        else:
            invalid.append(ch)
    return answers, invalid


def build_evaluation(questions, answers, correct=1, incorrect=0, unmarked=0):
    n = min(len(questions), len(answers))
    return {
        "source_type": "custom",
        "options": {
            "questions_in_order": questions[:n],
            "answers_in_order": answers[:n],
            "should_explain_scoring": False,
        },
        "marking_schemes": {
            "DEFAULT": {
                "correct": str(correct),
                "incorrect": str(incorrect),
                "unmarked": str(unmarked),
            }
        },
    }


def _write_png(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"Gagal menyimpan {path.name}")
    buf.tofile(str(path))


SECTIONS_FILE = "bagian.json"


def save_template_folder(folder, sheet, template, evaluation=None, sections=None):
    """Write template.json, config.json, evaluation.json and, for sheets
    without corner markers, the reference image used for alignment."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = ["template.json", "config.json"]
    if sheet.uses_markers:
        import src.processors.manager  # noqa: F401  (must load before any processor)
        from src.processors.AlignOnMarkers import fingerprint

        gray = cv2.cvtColor(sheet.page, cv2.COLOR_BGR2GRAY)
        _write_png(folder / ORIENTATION_FILENAME, fingerprint(gray))
        written.append(ORIENTATION_FILENAME)
    else:
        _write_png(folder / REFERENCE_FILENAME, cv2.cvtColor(sheet.page, cv2.COLOR_BGR2GRAY))
        written.append(REFERENCE_FILENAME)
    (folder / "template.json").write_text(json.dumps(template, indent=2), encoding="utf-8")
    (folder / "config.json").write_text(
        json.dumps(build_config(sheet.page_dims), indent=2), encoding="utf-8"
    )
    if evaluation:
        (folder / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        written.append("evaluation.json")
    if sections and any(sections.values()):
        # display names of the parts (template.json cannot hold them)
        (folder / SECTIONS_FILE).write_text(json.dumps(sections, indent=1, ensure_ascii=False), encoding="utf-8")
        written.append(SECTIONS_FILE)
    return written


def backup_existing(folder, names=("template.json", "config.json", "evaluation.json")):
    folder = Path(folder)
    for name in names:
        p = folder / name
        if p.exists():
            shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
