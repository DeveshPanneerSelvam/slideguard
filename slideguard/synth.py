"""Synthetic H&E-like slide tiles, with labeled scanning defects.

No real patient images. Tissue is drawn as pink (eosin-like) regions dotted with
purple (hematoxylin-like) nuclei on a near-white background. Each defect mimics a
common reason a scanned slide is not fit for an image model:

    blur          out-of-focus scan
    low_tissue    the scan caught mostly empty glass
    pen_mark      marker ink on the slide
    faded         weak, washed-out stain
    overstained   stain far too dark
"""

from pathlib import Path

import cv2
import numpy as np

SIZE = 384
DEFECTS = ["none", "blur", "low_tissue", "pen_mark", "faded", "overstained"]

BACKGROUND = (245, 242, 244)  # BGR, near-white glass
EOSIN = (200, 160, 232)  # BGR pink
NUCLEUS = (150, 60, 110)  # BGR purple
PEN_COLORS = [(40, 160, 40), (200, 60, 20), (25, 25, 25)]  # green, blue, black


def _tissue(rng: np.random.Generator, blobs: int, scale: float) -> np.ndarray:
    img = np.full((SIZE, SIZE, 3), BACKGROUND, np.uint8)
    mask = np.zeros((SIZE, SIZE), np.uint8)
    for _ in range(blobs):
        center = tuple(int(v) for v in rng.integers(40, SIZE - 40, 2))
        axes = tuple(int(v * scale) for v in rng.integers(60, 140, 2))
        cv2.ellipse(mask, center, axes, float(rng.uniform(0, 180)), 0, 360, 255, -1)
    shade = rng.normal(0, 10, (SIZE, SIZE, 3))
    tissue = np.clip(np.array(EOSIN, np.float32) + shade, 0, 255).astype(np.uint8)
    img[mask > 0] = tissue[mask > 0]
    ys, xs = np.nonzero(mask)
    if len(ys):
        for i in rng.choice(len(ys), size=min(len(ys) // 120, 900), replace=False):
            cv2.circle(img, (int(xs[i]), int(ys[i])), int(rng.integers(2, 5)), NUCLEUS, -1)
    noise = rng.normal(0, 3, img.shape)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def make_tile(defect: str, seed: int, mild: bool = False) -> np.ndarray:
    """mild=True makes a subtler version of the defect (harder to catch)."""
    if defect not in DEFECTS:
        raise ValueError(f"unknown defect {defect}")
    rng = np.random.default_rng(seed)
    if defect == "low_tissue":
        return _tissue(rng, blobs=2 if mild else 1, scale=0.5 if mild else 0.35)
    img = _tissue(rng, blobs=int(rng.integers(3, 6)), scale=1.0)
    if defect == "blur":
        k = int(rng.choice([5, 7])) if mild else int(rng.choice([15, 19, 23]))
        img = cv2.GaussianBlur(img, (k, k), 0)
    elif defect == "pen_mark":
        color = PEN_COLORS[int(rng.integers(len(PEN_COLORS)))]
        n_points = 2 if mild else 4
        points = rng.integers(20, SIZE - 20, (n_points, 2)).astype(np.int32)
        if mild:  # a short tick mark
            points[1] = points[0] + rng.integers(-40, 40, 2)
        cv2.polylines(img, [points], False, color, int(rng.integers(4, 7)) if mild else int(rng.integers(10, 18)))
    elif defect == "faded":
        alpha = float(rng.uniform(0.5, 0.6)) if mild else float(rng.uniform(0.25, 0.4))
        white = np.full_like(img, 250)
        img = cv2.addWeighted(img, alpha, white, 1 - alpha, 0)
    elif defect == "overstained":
        tissue = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1] > 25
        factor = rng.uniform(0.6, 0.7) if mild else rng.uniform(0.35, 0.5)
        dark = (img.astype(np.float32) * factor).astype(np.uint8)
        img[tissue] = dark[tissue]
    return img


def write_set(out_dir: Path, per_defect: dict[str, int], seed: int, prefix: str, mild_share: float = 0.0) -> list[dict]:
    """Write tiles as PNG; return rows of {slide_id, path, defect, mild}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, n = [], 0
    rng = np.random.default_rng(seed)
    for defect, count in per_defect.items():
        for _ in range(count):
            n += 1
            mild = defect != "none" and bool(rng.random() < mild_share)
            slide_id = f"{prefix}-{n:03d}"
            path = out_dir / f"{slide_id}.png"
            cv2.imwrite(str(path), make_tile(defect, seed * 10_000 + n, mild))
            rows.append({"slide_id": slide_id, "path": str(path), "defect": defect, "mild": mild})
    return rows
