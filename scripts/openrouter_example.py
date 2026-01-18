from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests


def to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/jpeg"
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def main() -> None:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Missing env OPENROUTER_API_KEY")

    image_path = Path(os.getenv("IMAGE_PATH", "test.jpg")).resolve()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    system_prompt = Path("backend/app/ai/system_prompt.txt").read_text(encoding="utf-8")
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2"),
        "temperature": 0.2,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请按系统要求输出 JSON。"},
                    {"type": "image_url", "image_url": {"url": to_data_url(image_path)}},
                ],
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000"),
        "X-Title": os.getenv("OPENROUTER_APP_NAME", "baby-meme-generator"),
    }

    url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=45)
    print("HTTP", resp.status_code)
    print(resp.text)


if __name__ == "__main__":
    main()

