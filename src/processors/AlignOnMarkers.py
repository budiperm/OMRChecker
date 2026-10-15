"""
Align a scan on the four solid squares printed near the corners of many
answer sheets (LJK), without cropping the page.

Unlike CropOnMarkers, which crops at the marker centres, this maps the four
markers found in the scan onto their positions in the blank sheet the
template was made from, so bubbles printed in line with the markers stay
inside the page.

Options:
  markerCenters: [[x, y] x4] where the marker centres must land, in
                 processing pixels (config dimensions; the template builder
                 makes these equal to pageDimensions), ordered top-left,
                 top-right, bottom-left, bottom-right
  markerSize:    marker width in processing pixels (used to reject other
                 dark shapes; default: any reasonable size)
  excludeFiles:  file names next to the template that are not answer sheets
                 (e.g. the blank scan the template was made from)
  orientationReference: small image of the blank sheet (next to the
                 template); sheets fed upside down are turned 180 degrees
"""

import itertools

import cv2
import numpy as np

from src.logger import logger
from src.processors.interfaces.ImagePreprocessor import ImagePreprocessor

DARK_THRESHOLD = 90


def find_corner_markers(gray, marker_size=None, target=None):
    """Solid dark squares near the four image corners.

    Returns a list of (x, y, w, h) ordered top-left, top-right, bottom-left,
    bottom-right, or None when four suitable squares are not found. With
    `target` (the template's marker centres) the squares must also be laid
    out like those."""
    h, w = gray.shape[:2]
    if marker_size:
        lo, hi = marker_size * 0.6, marker_size * 1.6
    else:
        lo, hi = w * 0.006, w * 0.05
    _, binary = cv2.threshold(gray, DARK_THRESHOLD, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if not (lo <= cw <= hi and lo <= ch <= hi and 0.75 <= cw / ch <= 1.33):
            continue
        # Solid square, even when the scan is a little rotated; filled bubbles
        # (round: ~0.79 of their enclosing square) are rejected
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        if rw * rh <= 0 or cv2.contourArea(c) < 0.88 * rw * rh:
            continue
        if gray[y : y + ch, x : x + cw].mean() > DARK_THRESHOLD:
            continue
        candidates.append((x, y, cw, ch))

    quadrants = []
    for qx, qy in ((0, 0), (w, 0), (0, h), (w, h)):
        in_quadrant = [
            r
            for r in candidates
            if ((r[0] + r[2] / 2 < w / 2) == (qx == 0))
            and ((r[1] + r[3] / 2 < h / 2) == (qy == 0))
        ]
        if not in_quadrant:
            return None
        in_quadrant.sort(key=lambda r: (r[0] + r[2] / 2 - qx) ** 2 + (r[1] + r[3] / 2 - qy) ** 2)
        quadrants.append(in_quadrant[:3])

    if target is None:  # blank sheet for a new template: nearest to each corner
        found = [q[0] for q in quadrants]
        return found if _similar_sizes(found) else None

    # Scans: the four squares must sit like the template's four (rotation,
    # shift and scale allowed, also slightly different across and down). A square cut off at the edge must not be
    # replaced by another dark square, e.g. an orientation mark next to it.
    best, best_error = None, None
    for combo in itertools.product(*quadrants):
        if not _similar_sizes(combo):
            continue
        error = _shape_error(marker_centers(combo), np.asarray(target, np.float32))
        if best_error is None or error < best_error:
            best, best_error = list(combo), error
    if best is None or best_error > SHAPE_TOLERANCE:
        return None
    return best


SHAPE_TOLERANCE = 0.025  # of the markers' diagonal: flatbed ~0.01%, phone photo ~1%, a wrong square ~5%


def _similar_sizes(rects):
    sizes = [max(r[2], r[3]) for r in rects]
    return max(sizes) <= 1.3 * min(sizes)


def _shape_error(found, target):
    """How far the four points are from the template's after the best affine
    map (rotation, shift, scale per axis), relative to the template's
    diagonal. Scans are near-affine; a wrong square breaks the shape."""
    matrix, _ = cv2.estimateAffine2D(found, target)
    if matrix is None:
        return float("inf")
    moved = found @ matrix[:, :2].T + matrix[:, 2]
    diagonal = float(np.hypot(*(target.max(axis=0) - target.min(axis=0))))
    return float(np.max(np.hypot(*(moved - target).T)) / diagonal)


def marker_centers(rects):
    return np.array([[x + w / 2, y + h / 2] for x, y, w, h in rects], dtype=np.float32)


FINGERPRINT_WIDTH = 120


def fingerprint(gray):
    """Small blurred copy of a page, for telling which way up it is."""
    h, w = gray.shape[:2]
    small = cv2.resize(gray, (FINGERPRINT_WIDTH, max(1, round(h * FINGERPRINT_WIDTH / w))), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(small, (3, 3), 0)


def likeness(a, b):
    """Normalized correlation of two fingerprints (-1..1)."""
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    return float(cv2.matchTemplate(a.astype(np.float32), b.astype(np.float32), cv2.TM_CCOEFF_NORMED)[0, 0])


class AlignOnMarkers(ImagePreprocessor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = np.array(self.options["markerCenters"], dtype=np.float32)
        self.marker_size = self.options.get("markerSize")
        self.excluded = [
            self.relative_dir.joinpath(name) for name in self.options.get("excludeFiles", [])
        ]
        self.reference = None
        name = self.options.get("orientationReference")
        if name:
            path = self.relative_dir.joinpath(name)
            data = np.fromfile(str(path), np.uint8) if path.exists() else None
            if data is not None:
                self.reference = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)

    def exclude_files(self):
        return self.excluded

    def align(self, image):
        rects = find_corner_markers(image, self.marker_size, self.target)
        if rects is None:
            return None
        matrix = cv2.getPerspectiveTransform(marker_centers(rects), self.target)
        h, w = image.shape[:2]
        return cv2.warpPerspective(
            image, matrix, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=255
        )

    def apply_filter(self, image, file_path):
        warped = self.align(image)
        if self.reference is None:
            if warped is None:
                logger.error(f"{file_path}: 4 corner markers not found (or one is cut off)")
            return warped
        # A sheet fed upside down has its four corner squares in the same
        # places: compare with the blank sheet to tell which way up it is.
        score = likeness(fingerprint(warped), self.reference) if warped is not None else -1.0
        if score < UPRIGHT_LIKENESS:
            turned = self.align(cv2.rotate(image, cv2.ROTATE_180))
            turned_score = likeness(fingerprint(turned), self.reference) if turned is not None else -1.0
            if turned_score > score:
                logger.warning(f"{file_path}: sheet was upside down, turned 180 degrees")
                warped, score = turned, turned_score
        if warped is None:
            logger.error(f"{file_path}: 4 corner markers not found (or one is cut off)")
        return warped


UPRIGHT_LIKENESS = 0.6  # filled sheets the right way up score ~0.8-0.95
