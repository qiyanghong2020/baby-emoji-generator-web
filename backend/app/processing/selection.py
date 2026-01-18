from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageFilter, ImageStat

from .meme_generator import OUTPUT_SIZE, auto_focus_square_crop, mouth_closeup_square_crop_global


CropType = Literal["face", "mouth"]


@dataclass(frozen=True)
class CropCandidate:
    src_index: int
    src_name: str
    crop_type: CropType
    score: float


def _to_512_rgb(img: Image.Image) -> Image.Image:
    return img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS).convert("RGB")


def score_512(img_512: Image.Image) -> float:
    small = img_512.convert("L").resize((128, 128), Image.Resampling.BILINEAR)
    stat = ImageStat.Stat(small)
    mean = (stat.mean[0] or 0.0) / 255.0
    std = (stat.stddev[0] or 0.0) / 255.0

    edges = small.filter(ImageFilter.FIND_EDGES)
    edge_mean = (ImageStat.Stat(edges).mean[0] or 0.0) / 255.0

    exposure = 1.0 - min(1.0, abs(mean - 0.55) / 0.55)
    contrast = min(1.0, std * 2.2)
    sharpness = min(1.0, edge_mean * 2.6)

    score = 0.52 * sharpness + 0.28 * exposure + 0.20 * contrast
    return max(0.0, min(1.0, float(score)))


def lip_redness_score_512(img_512: Image.Image) -> float:
    """
    Returns a rough 0..1 "mouth-likeness" score based on lip-redness density.
    This is a heuristic to avoid selecting mouth closeups when the detector fell back.
    """
    rgb = img_512.convert("RGB")
    w, h = rgb.size
    x1, x2 = int(w * 0.14), int(w * 0.86)
    y1, y2 = int(h * 0.32), int(h * 0.84)
    px = rgb.load()

    hit = 0
    total = 0
    intensity_sum = 0.0
    step = 4
    for y in range(y1, y2, step):
        for x in range(x1, x2, step):
            r, g, b = px[x, y]
            score = float(r) - 0.55 * float(g) - 0.45 * float(b)
            if score > 12.0:
                hit += 1
                intensity_sum += min(255.0, score) / 255.0
            total += 1
    if total <= 0 or hit <= 0:
        return 0.0
    density = hit / float(total)  # usually small
    intensity = intensity_sum / float(hit)

    # Density dominates (mouth pixels are sparse). Intensity mildly boosts confidence.
    d = min(1.0, density * 10.0)
    return max(0.0, min(1.0, d * (0.55 + 0.45 * intensity)))


def build_candidates(images: list[Image.Image], names: list[str], *, include_mouth: bool) -> list[CropCandidate]:
    out: list[CropCandidate] = []
    for idx, img in enumerate(images):
        src_name = names[idx] if idx < len(names) else f"image_{idx+1}"

        face_crop = _to_512_rgb(auto_focus_square_crop(img))
        face_score = score_512(face_crop)
        out.append(CropCandidate(src_index=idx, src_name=src_name, crop_type="face", score=face_score))

        if include_mouth:
            mouth_crop = _to_512_rgb(mouth_closeup_square_crop_global(img, variant=0))
            mouth_base = score_512(mouth_crop)
            mouth_lip = lip_redness_score_512(mouth_crop)
            combined = mouth_base * 0.55 + mouth_lip * 0.45
            if mouth_lip < 0.10:
                combined *= 0.65
            out.append(CropCandidate(src_index=idx, src_name=src_name, crop_type="mouth", score=float(combined)))
    return out


def pick_top_5(
    candidates: list[CropCandidate],
    *,
    max_mouth: int,
    target: int = 5,
) -> list[CropCandidate]:
    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)

    def _fill(selected: list[CropCandidate], max_per_image: int) -> list[CropCandidate]:
        per_image = defaultdict(int)
        mouth_count = 0
        for s in selected:
            per_image[s.src_index] += 1
            if s.crop_type == "mouth":
                mouth_count += 1

        selected_keys = {(s.src_index, s.crop_type) for s in selected}
        for cand in ranked:
            if len(selected) >= target:
                break
            key = (cand.src_index, cand.crop_type)
            if key in selected_keys:
                continue
            if per_image[cand.src_index] >= max_per_image:
                continue
            if cand.crop_type == "mouth" and mouth_count >= max_mouth:
                continue
            selected.append(cand)
            selected_keys.add(key)
            per_image[cand.src_index] += 1
            if cand.crop_type == "mouth":
                mouth_count += 1
        return selected

    selected: list[CropCandidate] = []
    selected = _fill(selected, max_per_image=1)
    if len(selected) < target:
        selected = _fill(selected, max_per_image=2)
    if len(selected) < target:
        selected = _fill(selected, max_per_image=3)
    if len(selected) < target:
        selected = _fill(selected, max_per_image=target)

    if not selected:
        selected = [ranked[0]]
    while len(selected) < target:
        selected.append(selected[len(selected) % len(selected)])

    return selected[:target]

