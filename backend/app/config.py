from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str | None
    openrouter_model: str
    openrouter_base_url: str
    openrouter_timeout_s: float
    openrouter_site_url: str | None
    openrouter_app_name: str | None
    openrouter_temperature: float
    openrouter_max_tokens: int

    generated_dir: Path
    frontend_dir: Path
    font_path: Path

    max_upload_bytes: int
    max_upload_total_bytes: int
    max_upload_files: int


def _resolve_path(value: str | None, base_dir: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def get_settings() -> Settings:
    backend_dir = Path(__file__).resolve().parents[1]
    project_root = Path(__file__).resolve().parents[2]

    generated_dir = _resolve_path(os.getenv("GENERATED_DIR"), backend_dir) or (backend_dir / "generated")
    frontend_dir = _resolve_path(os.getenv("FRONTEND_DIR"), project_root) or (project_root / "frontend")
    font_path = _resolve_path(os.getenv("FONT_PATH"), backend_dir) or (backend_dir / "assets" / "fonts" / "NotoSansSC-Regular.otf")

    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2"),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        openrouter_timeout_s=float(os.getenv("OPENROUTER_TIMEOUT_S", "45")),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL"),
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME"),
        openrouter_temperature=float(os.getenv("OPENROUTER_TEMPERATURE", "0.1")),
        openrouter_max_tokens=int(os.getenv("OPENROUTER_MAX_TOKENS", "1200")),
        generated_dir=generated_dir,
        frontend_dir=frontend_dir,
        font_path=font_path,
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        max_upload_total_bytes=int(os.getenv("MAX_UPLOAD_TOTAL_BYTES", str(40 * 1024 * 1024))),
        max_upload_files=int(os.getenv("MAX_UPLOAD_FILES", "8")),
    )
