from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..schemas import CropBox
from .utils import clamp


OUTPUT_SIZE = 512


@dataclass(frozen=True)
class GeneratedMeme:
    caption: str
    filename: str
    path: Path


def _io_bytes(data: bytes):
    import io

    return io.BytesIO(data)


def safe_open_image(image_bytes: bytes) -> tuple[Image.Image | None, str | None]:
    try:
        img = Image.open(_io_bytes(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        return img, None
    except Exception as e:
        return None, str(e)


def center_square_crop(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = int((w - side) / 2)
    top = int((h - side) / 2)
    return img.crop((left, top, left + side, top + side))


def _integral_image_2d(img_l: Image.Image) -> list[list[int]]:
    w, h = img_l.size
    pix = img_l.load()
    integral: list[list[int]] = [[0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        row_sum = 0
        out_row = integral[y + 1]
        prev_row = integral[y]
        for x in range(w):
            row_sum += int(pix[x, y])
            out_row[x + 1] = prev_row[x + 1] + row_sum
    return integral


def _rect_sum(integral: list[list[int]], x: int, y: int, side: int) -> int:
    x1, y1 = x, y
    x2, y2 = x + side, y + side
    return integral[y2][x2] - integral[y1][x2] - integral[y2][x1] + integral[y1][x1]


def auto_focus_square_crop(img: Image.Image) -> Image.Image:
    """
    Best-effort "feature focus" square crop for large images.
    Uses edge-density on a downscaled copy to pick a square region with more facial/texture details.
    Falls back to center crop when the heuristic can't find a stable answer.
    """
    w, h = img.size
    if min(w, h) < 96:
        return center_square_crop(img)

    max_side = max(w, h)
    target_max = 320
    ratio = 1.0
    small = img
    if max_side > target_max:
        ratio = target_max / float(max_side)
        small = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.Resampling.LANCZOS)

    sw, sh = small.size
    if min(sw, sh) < 96:
        return center_square_crop(img)

    edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
    integral = _integral_image_2d(edges)

    min_side = min(sw, sh)
    sizes = [int(min_side * s) for s in (0.45, 0.6, 0.78)]
    sizes = [s for s in sizes if s >= 96]
    if not sizes:
        return center_square_crop(img)

    cx, cy = sw / 2.0, sh / 2.0
    best_score = -1e9
    best = (int((sw - sizes[0]) / 2), int((sh - sizes[0]) / 2), sizes[0])

    grid = 10
    for side in sizes:
        max_x = max(0, sw - side)
        max_y = max(0, sh - side)
        if max_x == 0 and max_y == 0:
            candidates = [(0, 0)]
        else:
            candidates = []
            for yi in range(grid):
                y = int(max_y * yi / (grid - 1)) if grid > 1 else 0
                for xi in range(grid):
                    x = int(max_x * xi / (grid - 1)) if grid > 1 else 0
                    candidates.append((x, y))

        for x, y in candidates:
            s = _rect_sum(integral, x, y, side)
            density = s / float(max(1, side * side))

            wx = (x + side / 2.0) - cx
            wy = (y + side / 2.0) - cy
            dist = (wx * wx + wy * wy) ** 0.5
            dist_norm = dist / float(max(1.0, min_side / 2.0))
            score = density * (1.0 - 0.22 * min(1.0, dist_norm))

            if score > best_score:
                best_score = score
                best = (x, y, side)

    sx, sy, sside = best
    ox = int(sx / ratio)
    oy = int(sy / ratio)
    oside = int(sside / ratio)

    oside = min(oside, min(w, h))
    ox = max(0, min(w - oside, ox))
    oy = max(0, min(h - oside, oy))

    crop = img.crop((ox, oy, ox + oside, oy + oside))
    return center_square_crop(crop)


def _crop_rect_from_box(img: Image.Image, box: CropBox) -> tuple[Image.Image, int, int]:
    w, h = img.size
    left = int(clamp(float(box.x), 0.0, 1.0) * w)
    top = int(clamp(float(box.y), 0.0, 1.0) * h)
    bw = int(clamp(float(box.w), 0.05, 1.0) * w)
    bh = int(clamp(float(box.h), 0.05, 1.0) * h)
    right = max(left + 2, min(w, left + bw))
    bottom = max(top + 2, min(h, top + bh))
    left = max(0, min(w - 2, left))
    top = max(0, min(h - 2, top))
    roi = img.crop((left, top, right, bottom))
    return roi, left, top


def _locate_mouth_like_point(roi: Image.Image) -> tuple[float, float] | None:
    """
    Heuristic mouth locator: finds a centroid of "lip-like redness" within the ROI.
    Returns (x,y) in ROI coordinates, or None if signal is too weak.
    """
    rw, rh = roi.size
    if rw < 20 or rh < 20:
        return None

    target = 220
    scale = min(1.0, target / float(max(rw, rh)))
    small = roi
    if scale < 1.0:
        small = roi.resize((max(1, int(rw * scale)), max(1, int(rh * scale))), Image.Resampling.LANCZOS)

    sw, sh = small.size
    px = small.convert("RGB").load()

    x1 = int(sw * 0.12)
    x2 = int(sw * 0.88)
    y1 = int(sh * 0.30)
    y2 = int(sh * 0.86)
    if x2 <= x1 + 4 or y2 <= y1 + 4:
        return None

    sum_w = 0.0
    sum_x = 0.0
    sum_y = 0.0
    max_score = 0.0

    for y in range(y1, y2):
        for x in range(x1, x2):
            r, g, b = px[x, y]
            # "Lip score" favors redder pixels; bib/clothes (white/gray) tend to score low.
            score = float(r) - 0.55 * float(g) - 0.45 * float(b)
            if score <= 6.0:
                continue
            # Mild saturation boost.
            sat = float(max(r, g, b) - min(r, g, b))
            wgt = score * (0.6 + sat / 255.0)
            sum_w += wgt
            sum_x += wgt * x
            sum_y += wgt * y
            if score > max_score:
                max_score = score

    if sum_w <= 1e-6 or max_score < 14.0:
        return None

    cx = sum_x / sum_w
    cy = sum_y / sum_w
    # back to ROI coordinate space
    cx = cx / float(sw) * float(rw)
    cy = cy / float(sh) * float(rh)
    return cx, cy


def mouth_closeup_square_crop(img: Image.Image, box: CropBox, variant: int) -> Image.Image:
    """
    Crop a square around the mouth using a lip-redness heuristic inside the given box.
    Designed to keep the mouth fully visible while minimizing bib/clothes.
    """
    roi, ox, oy = _crop_rect_from_box(img, box)
    rw, rh = roi.size
    roi_min = float(min(rw, rh))

    mouth = _locate_mouth_like_point(roi)
    if mouth is None:
        # Fallback: mouth is usually around lower-middle of face ROI.
        cx = rw * 0.50
        cy = rh * 0.56
    else:
        cx, cy = mouth

    # Keep the focus from drifting too low into bib/clothes.
    cy = min(cy, rh * 0.64)

    # Square size: big enough to include full mouth + margin; not too big to avoid bib.
    side = roi_min * 0.52
    side = max(roi_min * 0.38, min(roi_min * 0.70, side))

    # Slight offsets across the 5 images to avoid edge-cutting.
    offsets = [(0.0, 0.0), (-0.05, 0.0), (0.05, 0.0), (0.0, -0.05), (0.0, 0.05)]
    dx, dy = offsets[variant % len(offsets)]
    cx += dx * side
    cy += dy * side

    # Put mouth slightly above center to preserve lips/chin without cutting top lip.
    cy += 0.06 * side

    left = int(max(0, min(rw - side, cx - side / 2.0)))
    top = int(max(0, min(rh - side, cy - side / 2.0)))
    right = int(min(rw, left + side))
    bottom = int(min(rh, top + side))

    crop = roi.crop((left, top, right, bottom))
    # Ensure square (rounding may have introduced 1px diff).
    crop = center_square_crop(crop)
    return crop


def mouth_closeup_square_crop_global(img: Image.Image, variant: int) -> Image.Image:
    """
    Mouth closeup without an AI box. Searches for lip-like redness in the top portion of the image
    (to avoid bib/clothes), then crops a square around it.
    """
    w, h = img.size
    search_h = int(h * 0.78)
    roi = img.crop((0, 0, w, max(1, search_h)))
    mouth = _locate_mouth_like_point(roi)

    if mouth is None:
        # Last resort: avoid bottom clothing; bias to upper-middle.
        cx = w * 0.50
        cy = h * 0.42
        side = min(w, h) * 0.42
    else:
        mx, my = mouth
        cx = mx
        cy = my
        # Keep mouth in frame with a reasonable closeup size.
        side = min(w, h) * 0.34

    side = max(min(w, h) * 0.26, min(min(w, h) * 0.55, side))

    offsets = [(0.0, 0.0), (-0.05, 0.0), (0.05, 0.0), (0.0, -0.05), (0.0, 0.05)]
    dx, dy = offsets[variant % len(offsets)]
    cx += dx * side
    cy += dy * side
    cy += 0.06 * side

    # Clamp so we don't drift into the very bottom.
    cy = min(cy, h * 0.72)

    left = int(max(0, min(w - side, cx - side / 2.0)))
    top = int(max(0, min(h - side, cy - side / 2.0)))
    crop = img.crop((left, top, int(left + side), int(top + side)))
    return center_square_crop(crop)


def square_from_box(img: Image.Image, box: CropBox) -> Image.Image:
    w, h = img.size

    left = clamp(box.x, 0.0, 1.0) * w
    top = clamp(box.y, 0.0, 1.0) * h
    bw = clamp(box.w, 0.05, 1.0) * w
    bh = clamp(box.h, 0.05, 1.0) * h

    cx = left + bw / 2
    cy = top + bh / 2
    side = min(max(1.0, min(bw, bh)), float(min(w, h)))

    half = side / 2
    l = cx - half
    t = cy - half
    r = cx + half
    b = cy + half

    if l < 0:
        r -= l
        l = 0
    if t < 0:
        b -= t
        t = 0
    if r > w:
        l -= (r - w)
        r = w
    if b > h:
        t -= (b - h)
        b = h

    l = int(max(0, math.floor(l)))
    t = int(max(0, math.floor(t)))
    r = int(min(w, math.ceil(r)))
    b = int(min(h, math.ceil(b)))

    if r - l <= 10 or b - t <= 10:
        return auto_focus_square_crop(img)

    crop = img.crop((l, t, r, b))
    return center_square_crop(crop)


def _load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size=size)

    fallback_candidates = [
        os.getenv("WINDIR", "C:\\Windows") + "\\Fonts\\msyh.ttc",
        os.getenv("WINDIR", "C:\\Windows") + "\\Fonts\\simhei.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for cand in fallback_candidates:
        try:
            if Path(cand).exists():
                return ImageFont.truetype(cand, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    s = (text or "").strip()
    if not s:
        return ["收到"]

    lines: list[str] = []
    current = ""
    for ch in s:
        test = current + ch
        bbox = draw.textbbox((0, 0), test, font=font, stroke_width=0)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _fit_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    max_width: int,
    max_height: int,
    max_lines: int,
) -> tuple[str, ImageFont.ImageFont]:
    for size in range(64, 24, -2):
        font = _load_font(font_path, size=size)
        lines = _wrap_text(draw, text, font, max_width=max_width)
        if len(lines) > max_lines:
            continue

        candidate = "\n".join(lines)
        bbox = draw.multiline_textbbox((0, 0), candidate, font=font, spacing=6, align="center", stroke_width=6)
        h = bbox[3] - bbox[1]
        w = bbox[2] - bbox[0]
        if w <= max_width and h <= max_height:
            return candidate, font
    return text, _load_font(font_path, size=24)


def render_caption_onto_512(img_512: Image.Image, caption: str, font_path: Path) -> Image.Image:
    base = img_512.convert("RGBA")
    draw = ImageDraw.Draw(base)

    margin_x = 26
    max_width = OUTPUT_SIZE - margin_x * 2
    max_height = 170

    text, font = _fit_text_lines(draw, caption, font_path, max_width=max_width, max_height=max_height, max_lines=3)
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=6, align="center", stroke_width=6)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad_y = 14
    y = OUTPUT_SIZE - pad_y - text_h
    y = max(12, y)
    x = int((OUTPUT_SIZE - text_w) / 2 - bbox[0])

    rect_top = max(0, int(y - 12))
    rect = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rect_draw = ImageDraw.Draw(rect)
    rect_draw.rectangle([0, rect_top, OUTPUT_SIZE, OUTPUT_SIZE], fill=(0, 0, 0, 120))
    base = Image.alpha_composite(base, rect)

    draw = ImageDraw.Draw(base)
    draw.multiline_text(
        (x, y),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        align="center",
        spacing=6,
        stroke_width=6,
        stroke_fill=(0, 0, 0, 255),
    )
    return base.convert("RGBA")


def make_text_only_512(caption: str, font_path: Path) -> Image.Image:
    palettes = [
        (248, 250, 252),
        (255, 247, 237),
        (240, 253, 250),
        (245, 243, 255),
        (254, 242, 242),
    ]
    bg = random.choice(palettes)
    img = Image.new("RGBA", (OUTPUT_SIZE, OUTPUT_SIZE), (*bg, 255))
    return render_caption_onto_512(img, caption, font_path)


def make_512_crops(img: Image.Image, crop_boxes: list[CropBox] | None, crop_preference: str) -> list[Image.Image]:
    crops: list[Image.Image] = []
    for i in range(5):
        box = None
        if crop_boxes:
            box = crop_boxes[i] if i < len(crop_boxes) else crop_boxes[0]

        if crop_preference == "mouth_closeup":
            crop = mouth_closeup_square_crop(img, box, variant=i) if box is not None else mouth_closeup_square_crop_global(img, variant=i)
        elif box is not None:
            crop = square_from_box(img, box)
        else:
            crop = auto_focus_square_crop(img)

        crop = crop.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
        crops.append(crop.convert("RGBA"))
    return crops


def make_montage_3x2(crops_512: list[Image.Image]) -> Image.Image:
    """
    3 columns x 2 rows montage:
    top: #1 #2 #3
    bottom: #4 #5 (rightmost is blank)
    """
    bg = (20, 24, 32, 255)
    canvas = Image.new("RGBA", (OUTPUT_SIZE * 3, OUTPUT_SIZE * 2), bg)
    for idx, crop in enumerate(crops_512[:5]):
        row = 0 if idx < 3 else 1
        col = idx if idx < 3 else (idx - 3)
        x = col * OUTPUT_SIZE
        y = row * OUTPUT_SIZE
        canvas.alpha_composite(crop.convert("RGBA"), (x, y))
    return canvas


def save_memes_from_crops(
    crops_512: list[Image.Image],
    captions: list[str],
    out_dir: Path,
    request_id: str,
    font_path: Path,
) -> list[GeneratedMeme]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[GeneratedMeme] = []
    for i in range(5):
        caption = captions[i] if i < len(captions) else "收到"
        filename = f"{request_id}_{i+1}.png"
        path = out_dir / filename
        try:
            base = crops_512[i] if i < len(crops_512) else crops_512[0]
            final = render_caption_onto_512(base, caption, font_path)
            final.save(path, format="PNG", optimize=True)
            results.append(GeneratedMeme(caption=caption, filename=filename, path=path))
        except Exception:
            final = make_text_only_512("收到", font_path)
            final.save(path, format="PNG", optimize=True)
            results.append(GeneratedMeme(caption="收到", filename=filename, path=path))
    return results


def generate_memes(
    img: Image.Image | None,
    crop_boxes: list[CropBox] | None,
    captions: list[str],
    out_dir: Path,
    request_id: str,
    font_path: Path,
    crop_preference: str = "",
) -> list[GeneratedMeme]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[GeneratedMeme] = []
    crops_512: list[Image.Image] | None = None
    if img is not None:
        crops_512 = make_512_crops(img, crop_boxes=crop_boxes, crop_preference=crop_preference)

    for i in range(5):
        caption = captions[i] if i < len(captions) else "收到"
        filename = f"{request_id}_{i+1}.png"
        path = out_dir / filename

        try:
            if img is None:
                final = make_text_only_512(caption, font_path)
            else:
                final = render_caption_onto_512(crops_512[i], caption, font_path)  # type: ignore[index]

            final.save(path, format="PNG", optimize=True)
            results.append(GeneratedMeme(caption=caption, filename=filename, path=path))
        except Exception:
            final = make_text_only_512("收到", font_path)
            final.save(path, format="PNG", optimize=True)
            results.append(GeneratedMeme(caption="收到", filename=filename, path=path))

    return results
