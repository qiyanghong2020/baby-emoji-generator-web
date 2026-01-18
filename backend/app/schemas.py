from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ExpressionLabel = Literal["开心", "委屈", "生气", "震惊", "困", "不确定"]


class ImageQuality(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    usable: bool


class ExpressionAnalysis(BaseModel):
    primary_label: ExpressionLabel
    confidence: float = Field(..., ge=0.0, le=1.0)
    notes: str = ""


class CropBox(BaseModel):
    x: float = Field(..., description="left position, 0..1")
    y: float = Field(..., description="top position, 0..1")
    w: float = Field(..., description="width, 0..1")
    h: float = Field(..., description="height, 0..1")
    reason: str = ""

    @field_validator("x", "y")
    @classmethod
    def _clamp_pos(cls, value: float) -> float:
        try:
            value = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, value))

    @field_validator("w", "h")
    @classmethod
    def _clamp_size(cls, value: float) -> float:
        try:
            value = float(value)
        except Exception:
            return 1.0
        return max(0.05, min(1.0, value))


class CropPlan(BaseModel):
    strategy: Literal["face_focus", "upper_face", "mouth_focus", "center_square", "unknown"] = "unknown"
    boxes: list[CropBox] = Field(default_factory=list, description="Prefer 5 boxes; 1 is acceptable as fallback")
    assumptions: str = ""


class Caption(BaseModel):
    text: str = Field(..., min_length=1, max_length=60)
    tone: Literal["温柔", "搞笑", "多梗", "中性"] = "中性"
    safety_notes: str = ""


class Safety(BaseModel):
    allowed: bool
    risk: Literal["low", "medium", "high"] = "low"
    reasons: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)


class Fallback(BaseModel):
    use_fallback: bool
    reason: str = ""
    suggestions: list[str] = Field(default_factory=list)


class AIResult(BaseModel):
    image_quality: ImageQuality
    expression_analysis: ExpressionAnalysis
    crop_plan: CropPlan
    captions: list[Caption] = Field(default_factory=list)
    safety: Safety
    fallback: Fallback


class CaptionsResult(BaseModel):
    captions: list[Caption] = Field(default_factory=list)
    safety: Safety
    fallback: Fallback

    @field_validator("captions")
    @classmethod
    def _captions_len_5(cls, value: list[Caption]) -> list[Caption]:
        if len(value) != 5:
            raise ValueError("captions must have length 5")
        return value
