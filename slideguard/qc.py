"""Explainable quality checks for a scanned slide tile.

Each check computes one number a lab person can understand, compares it to a
threshold, and reports the reason when it fails. No black box: the point is to
decide whether an image is fit to send to a downstream AI model.

Thresholds were tuned on a development set (seed 1) and are evaluated on a
separate held-out golden set (evals/), so the eval is not grading its own homework.
"""

from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

THRESHOLDS = {
    "min_tissue_fraction": 0.15,   # share of the image that is tissue
    "min_sharpness": 250.0,        # variance of the Laplacian inside tissue
    "max_pen_fraction": 0.0002,    # share of pixels that look like marker ink
    "min_stain_saturation": 60.0,  # mean HSV saturation inside tissue (0-255)
    "min_stain_brightness": 150.0, # mean HSV value inside tissue (0-255)
}


@dataclass
class QCResult:
    passed: bool
    metrics: dict[str, float]
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _masks(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    # Marker ink: green-to-blue hues (H&E is pink/purple), or near-black.
    pen = (((h >= 35) & (h <= 125) & (s > 90)) | (v < 45))
    pen = cv2.morphologyEx(pen.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    tissue = (s > 15) & ~pen
    return tissue, pen


def measure(img: np.ndarray) -> dict[str, float]:
    tissue, pen = _masks(img)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    inner = cv2.erode(tissue.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    region = inner if inner.sum() > 500 else tissue
    has_tissue = region.sum() > 0
    return {
        "tissue_fraction": round(float(tissue.mean()), 4),
        "sharpness": round(float(lap[region].var()) if has_tissue else 0.0, 1),
        "pen_fraction": round(float(pen.mean()), 4),
        "stain_saturation": round(float(hsv[:, :, 1][tissue].mean()) if tissue.any() else 0.0, 1),
        "stain_brightness": round(float(hsv[:, :, 2][tissue].mean()) if tissue.any() else 0.0, 1),
    }


def check(img: np.ndarray, thresholds: dict[str, float] | None = None) -> QCResult:
    t = {**THRESHOLDS, **(thresholds or {})}
    m = measure(img)
    failures = []
    if m["tissue_fraction"] < t["min_tissue_fraction"]:
        failures.append(f"low_tissue: {m['tissue_fraction']:.0%} tissue (needs {t['min_tissue_fraction']:.0%}+)")
    if m["pen_fraction"] > t["max_pen_fraction"]:
        failures.append(f"pen_mark: {m['pen_fraction']:.1%} of image looks like ink (max {t['max_pen_fraction']:.1%})")
    if m["tissue_fraction"] >= t["min_tissue_fraction"]:
        if m["sharpness"] < t["min_sharpness"]:
            failures.append(f"blur: sharpness {m['sharpness']:.0f} (needs {t['min_sharpness']:.0f}+)")
        if m["stain_brightness"] < t["min_stain_brightness"]:
            failures.append(f"overstained: brightness {m['stain_brightness']:.0f} (needs {t['min_stain_brightness']:.0f}+)")
        elif m["stain_saturation"] < t["min_stain_saturation"]:
            failures.append(f"faded: stain saturation {m['stain_saturation']:.0f} (needs {t['min_stain_saturation']:.0f}+)")
    return QCResult(passed=not failures, metrics=m, failures=failures)


def check_file(path: str) -> QCResult:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return QCResult(False, {}, [f"unreadable: could not open {path}"])
    return check(img)


def failure_codes(result: QCResult) -> set[str]:
    return {f.split(":")[0] for f in result.failures}
