from __future__ import annotations

import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai.openrouter_client import OpenRouterClient
from .config import get_settings
from .processing.meme_generator import make_512_crops, make_montage_3x2, safe_open_image, save_memes_from_crops
from .processing.safety import (
    DEFAULT_SUGGESTIONS,
    detect_crop_preference,
    ensure_5_safe_captions,
    pick_expression_label,
    sanitize_user_prompt,
)
from .processing.utils import extract_json_object
from .schemas import AIResult, CaptionsResult, CropBox
from .processing.captions_fallback import get_mouth_closeup_captions

logger = logging.getLogger("baby-meme")


def _guess_mime(content_type: str | None, filename: str | None) -> str:
    ct = (content_type or "").lower().strip()
    if ct.startswith("image/"):
        return ct
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def _normalize_boxes(boxes: list[CropBox]) -> list[CropBox]:
    if not boxes:
        return []
    if len(boxes) >= 5:
        return boxes[:5]
    while len(boxes) < 5:
        boxes.append(boxes[-1])
    return boxes


def _apply_mouth_closeup(boxes: list[CropBox]) -> list[CropBox]:
    # Kept for backward compatibility; mouth closeup cropping is implemented in the image pipeline
    # (uses pixel heuristics to keep the mouth fully visible).
    return boxes


def _extract_caption_texts(ai: AIResult) -> list[str]:
    return [c.text for c in (ai.captions or [])]


def _safe_public_url(prefix: str, filename: str) -> str:
    prefix = "/" + prefix.strip("/") + "/"
    return f"{prefix}{filename}"


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Ensure `.env` is found regardless of the current working directory.
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")
settings = get_settings()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="宝宝表情包生成器", version="1.0.0")

openrouter = OpenRouterClient(settings=settings)


def _write_debug_text(out_dir: Path, filename: str, parts: list[str]) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    text = "\n\n---\n\n".join([p for p in parts if p])
    path.write_text(text, encoding="utf-8", errors="replace")
    return _safe_public_url("generated", filename)


@app.post("/upload")
async def upload(file: UploadFile = File(...), prompt: str | None = Form(None)):
    request_id = uuid.uuid4().hex

    image_bytes = await file.read()
    if not image_bytes:
        return JSONResponse(
            status_code=400,
            content={"error": "empty_upload", "message": "没有收到图片文件", "request_id": request_id},
        )
    if len(image_bytes) > settings.max_upload_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "error": "file_too_large",
                "message": f"图片过大（>{settings.max_upload_bytes} bytes）",
                "request_id": request_id,
            },
        )

    mime_type = _guess_mime(file.content_type, file.filename)
    img, img_err = safe_open_image(image_bytes)

    used_ai = False  # true only when we accepted and used the AI plan
    ai_attempted = False
    ai_error_stage = ""
    ai_error = ""
    ai_calls = 0
    fallback_used = False
    fallback_reason = ""
    suggestions: list[str] = []
    expression_label = "不确定"
    expression_notes = ""
    user_prompt, user_prompt_status = sanitize_user_prompt(prompt)
    crop_preference = detect_crop_preference(user_prompt)
    user_prompt_for_ai = user_prompt
    if crop_preference == "mouth_closeup" and user_prompt_for_ai:
        user_prompt_for_ai = (
            f"{user_prompt_for_ai}"
            "（裁剪硬约束：嘴巴必须完整可见，左右上下要留出安全边距；尽量只取嘴巴/嘴唇与口水区域，尽量避免口水巾/衣服）"
        )

    crop_boxes: list[CropBox] = []
    captions: list[str] = []
    captions_ai_used = False
    captions_ai_error = ""
    captions_source = "fallback"
    ai_debug_url = ""
    captions_debug_url = ""

    if img is None:
        fallback_used = True
        fallback_reason = f"图片读取失败：{img_err or 'unknown'}"
        suggestions = DEFAULT_SUGGESTIONS
        captions, _ = ensure_5_safe_captions([], "不确定")
    else:
        ai_obj: AIResult | None = None
        ai_error_msg: str | None = None
        ai_debug_parts: list[str] = []

        def _call_ai(strict_retry: bool, hint: str | None, previous_output: str | None) -> str:
            nonlocal ai_attempted, ai_error_stage, ai_error, ai_calls
            ai_attempted = True
            ai_calls += 1
            raw = openrouter.analyze_image(
                image_bytes=image_bytes,
                mime_type=mime_type,
                user_prompt=user_prompt_for_ai,
                previous_output=previous_output,
                strict_retry=strict_retry,
                error_hint=hint,
            )
            ai_debug_parts.append(raw.content_text or "")
            return raw.content_text

        def _try_ai() -> AIResult | None:
            nonlocal ai_error_stage, ai_error
            content1 = _call_ai(strict_retry=False, hint=None, previous_output=None)
            try:
                parsed1 = extract_json_object(content1)
            except Exception as e1:
                ai_error_stage = "parse"
                ai_error = str(e1)
                content2 = _call_ai(strict_retry=True, hint=str(e1), previous_output=content1)
                parsed2 = extract_json_object(content2)
                obj2 = AIResult.model_validate(parsed2)
                ai_error_stage = ""
                ai_error = ""
                return obj2

            try:
                obj1 = AIResult.model_validate(parsed1)
                ai_error_stage = ""
                ai_error = ""
                return obj1
            except Exception as e1:
                ai_error_stage = "validate"
                ai_error = str(e1)
                content2 = _call_ai(strict_retry=True, hint=str(e1), previous_output=content1)
                parsed2 = extract_json_object(content2)
                obj2 = AIResult.model_validate(parsed2)
                ai_error_stage = ""
                ai_error = ""
                return obj2
            try:
                parsed = extract_json_object(raw.content_text)
            except Exception as e:
                ai_error_stage = "parse"
                ai_error = str(e)
                raise
            try:
                return AIResult.model_validate(parsed)
            except Exception as e:
                ai_error_stage = "validate"
                ai_error = str(e)
                raise

        if settings.openrouter_api_key:
            try:
                ai_obj = _try_ai()
                used_ai = True
            except Exception as e:
                ai_error_msg = str(e)
                if ai_debug_parts:
                    ai_debug_url = _write_debug_text(
                        Path(settings.generated_dir),
                        f"{request_id}_ai_plan_debug.txt",
                        ai_debug_parts,
                    )
        else:
            ai_error_msg = "OPENROUTER_API_KEY 未配置，已启用本地兜底流程"

        if ai_obj is None:
            fallback_used = True
            # Mark as "http" if we never reached parse/validate stages.
            if ai_attempted and not ai_error_stage:
                ai_error_stage = "http"
                ai_error = ai_error_msg or ai_error or "AI 请求失败"
            fallback_reason = ai_error_msg or ai_error or "AI 解析失败"
            suggestions = DEFAULT_SUGGESTIONS
            expression_label = "不确定"
            captions, _ = ensure_5_safe_captions([], "不确定")
            crop_boxes = []
        else:
            expression_label = pick_expression_label(ai_obj.expression_analysis.primary_label)
            expression_notes = (ai_obj.expression_analysis.notes or "").strip()

            if (not ai_obj.safety.allowed) or (ai_obj.safety.risk == "high") or ai_obj.fallback.use_fallback:
                fallback_used = True
                reasons = []
                if not ai_obj.safety.allowed:
                    reasons.append("safety 不通过")
                if ai_obj.safety.risk == "high":
                    reasons.append("risk=high")
                if ai_obj.fallback.use_fallback:
                    reasons.append(f"model_fallback: {ai_obj.fallback.reason}".strip())
                fallback_reason = "；".join([r for r in reasons if r]) or "启用回退"
                suggestions = (ai_obj.fallback.suggestions or []) or DEFAULT_SUGGESTIONS

            model_captions = _extract_caption_texts(ai_obj)
            captions, caption_fallback = ensure_5_safe_captions(model_captions, expression_label)
            if caption_fallback:
                fallback_used = True
                fallback_reason = fallback_reason or "文案合规过滤触发兜底"
                suggestions = suggestions or DEFAULT_SUGGESTIONS
            else:
                captions_source = "ai_original"

            if not fallback_used:
                crop_boxes = _normalize_boxes(ai_obj.crop_plan.boxes)
                if crop_preference == "mouth_closeup" and crop_boxes:
                    crop_boxes = _apply_mouth_closeup(crop_boxes)
            else:
                crop_boxes = []

    out_dir = Path(settings.generated_dir)
    if img is None:
        # image unreadable -> text-only
        from .processing.meme_generator import generate_memes

        memes = generate_memes(
            img=None,
            crop_boxes=None,
            captions=captions,
            out_dir=out_dir,
            request_id=request_id,
            font_path=Path(settings.font_path),
            crop_preference="",
        )
    else:
        # If user explicitly wants mouth closeups, prefer a mouth-themed baseline even before AI refinement.
        if crop_preference == "mouth_closeup":
            captions, _ = ensure_5_safe_captions(get_mouth_closeup_captions(5), "不确定")
            captions_source = "mouth_fallback"

        crops_512 = make_512_crops(img, crop_boxes=crop_boxes, crop_preference=crop_preference)

        # Second-pass captions: align with the FINAL crops (the actual meme subject), not the original photo.
        if settings.openrouter_api_key:
            cap_debug_parts: list[str] = []
            try:
                import io

                montage = make_montage_3x2(crops_512)
                buf = io.BytesIO()
                montage.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
                montage_bytes = buf.getvalue()

                raw2 = openrouter.captions_for_montage(montage_bytes, "image/jpeg", user_prompt=user_prompt, strict_retry=False, error_hint=None)
                cap_debug_parts.append(raw2.content_text or "")
                try:
                    parsed2 = extract_json_object(raw2.content_text)
                    cap_obj = CaptionsResult.model_validate(parsed2)
                except Exception as e0:
                    raw2b = openrouter.captions_for_montage(montage_bytes, "image/jpeg", user_prompt=user_prompt, strict_retry=True, error_hint=str(e0))
                    cap_debug_parts.append(raw2b.content_text or "")
                    parsed2b = extract_json_object(raw2b.content_text)
                    cap_obj = CaptionsResult.model_validate(parsed2b)
                if (not cap_obj.safety.allowed) or (cap_obj.safety.risk == "high") or cap_obj.fallback.use_fallback:
                    raise RuntimeError("captions_safety_fallback")

                captions2, caption2_fallback = ensure_5_safe_captions([c.text for c in cap_obj.captions], expression_label)
                if caption2_fallback:
                    raise RuntimeError("captions_filtered")

                captions = captions2
                captions_ai_used = True
                captions_source = "ai_crops"
            except Exception as e:
                captions_ai_error = str(e)
                if cap_debug_parts:
                    captions_debug_url = _write_debug_text(
                        Path(settings.generated_dir),
                        f"{request_id}_ai_captions_debug.txt",
                        cap_debug_parts,
                    )

        memes = save_memes_from_crops(
            crops_512=crops_512,
            captions=captions,
            out_dir=out_dir,
            request_id=request_id,
            font_path=Path(settings.font_path),
        )

    results = [{"caption": m.caption, "url": _safe_public_url("generated", m.filename)} for m in memes]

    return {
        "request_id": request_id,
        "used_ai": used_ai,
        "ai_attempted": ai_attempted,
        "ai_calls": ai_calls,
        "ai_error_stage": ai_error_stage,
        "ai_error": ai_error,
        "user_prompt": user_prompt or "",
        "user_prompt_status": user_prompt_status,
        "crop_preference": crop_preference,
        "captions_ai_used": captions_ai_used,
        "captions_ai_error": captions_ai_error,
        "captions_source": captions_source,
        "captions_aligned_to_crops": bool(captions_ai_used and captions_source == "ai_crops"),
        "ai_debug_url": ai_debug_url,
        "captions_debug_url": captions_debug_url,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "expression_label": expression_label,
        "expression_notes": expression_notes,
        "results": results,
        "suggestions": suggestions,
    }


def _mount_static() -> None:
    generated_dir = Path(settings.generated_dir)
    generated_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/generated", StaticFiles(directory=str(generated_dir)), name="generated")

    frontend_dir = Path(settings.frontend_dir)
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    else:
        logger.warning("Frontend directory not found: %s", frontend_dir)


_mount_static()
