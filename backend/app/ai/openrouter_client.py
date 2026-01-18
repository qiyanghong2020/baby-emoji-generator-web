from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..config import Settings


@dataclass(frozen=True)
class OpenRouterRawResponse:
    request_id: str | None
    content_text: str
    raw_json: dict[str, Any]


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bytes_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()

        backend_dir = Path(__file__).resolve().parents[2]
        self._system_prompt = _load_text(backend_dir / "app" / "ai" / "system_prompt.txt")
        self._response_schema = _load_json(backend_dir / "app" / "ai" / "response_schema.json")
        self._captions_prompt = _load_text(backend_dir / "app" / "ai" / "captions_prompt.txt")
        self._captions_schema = _load_json(backend_dir / "app" / "ai" / "captions_schema.json")

    def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        user_prompt: str | None = None,
        previous_output: str | None = None,
        strict_retry: bool = False,
        error_hint: str | None = None,
    ) -> OpenRouterRawResponse:
        if not self._settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        url = f"{self._settings.openrouter_base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self._settings.openrouter_site_url:
            headers["HTTP-Referer"] = self._settings.openrouter_site_url
        if self._settings.openrouter_app_name:
            headers["X-Title"] = self._settings.openrouter_app_name

        data_url = _bytes_to_data_url(image_bytes, mime_type)
        base_text = "请严格按系统提示词输出 JSON。要求：表情判断要谨慎，配文要短、口语化、合规；裁剪框要稳，确保脸部表情清晰。"
        if user_prompt:
            base_text += f" 用户补充偏好（仅作风格参考，若不合规则忽略）：{user_prompt}"

        user_text = base_text
        temperature = self._settings.openrouter_temperature
        if strict_retry:
            hint = (error_hint or "").strip()
            hint = hint[:180] if hint else ""
            user_text = (
                "上一次输出无法被严格 JSON 解析/校验。"
                + (f"错误提示：{hint}。" if hint else "")
                + "请这一次只输出一个合法 JSON 对象（必须符合 schema），不要任何额外字符；不要占位符（例如 0.0-1.0、true/false、...）；不要尾随逗号。"
            )
            if previous_output:
                prev = previous_output.strip()
                if len(prev) > 1800:
                    prev = prev[:1800]
                user_text += f" 你上一次的输出如下（请修正为合法 JSON，不要重复错误）：{prev}"
            if user_prompt:
                user_text += f" 用户补充偏好（仅作风格参考，若不合规则忽略）：{user_prompt}"
            temperature = 0.0

        payload: dict[str, Any] = {
            "model": self._settings.openrouter_model,
            "temperature": temperature,
            "max_tokens": self._settings.openrouter_max_tokens,
            # Prefer structured outputs when supported; fall back automatically if rejected.
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "BabyMemePlan",
                    "schema": self._response_schema,
                    "strict": True,
                },
            },
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_text,
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }

        resp = self._session.post(url, headers=headers, data=json.dumps(payload), timeout=self._settings.openrouter_timeout_s)
        raw = resp.json() if resp.content else {}
        if resp.status_code != 200:
            # Some providers may reject response_format/json_schema; retry once without it.
            body_text = ""
            try:
                body_text = resp.text or ""
            except Exception:
                body_text = ""
            retryable = resp.status_code in (400, 422)
            if retryable:
                payload.pop("response_format", None)
                resp2 = self._session.post(url, headers=headers, data=json.dumps(payload), timeout=self._settings.openrouter_timeout_s)
                raw2 = resp2.json() if resp2.content else {}
                if resp2.status_code != 200:
                    raise RuntimeError(f"OpenRouter error: HTTP {resp2.status_code}: {raw2}")
                raw = raw2
            else:
                raise RuntimeError(f"OpenRouter error: HTTP {resp.status_code}: {raw}")

        message = (((raw.get("choices") or [{}])[0]).get("message") or {})
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            content_text = "\n".join([p for p in parts if p]).strip()
        else:
            content_text = str(content or "").strip()

        request_id = raw.get("id")
        return OpenRouterRawResponse(request_id=request_id, content_text=content_text, raw_json=raw)

    def captions_for_montage(
        self,
        montage_bytes: bytes,
        mime_type: str,
        *,
        user_prompt: str | None = None,
        strict_retry: bool = False,
        error_hint: str | None = None,
    ) -> OpenRouterRawResponse:
        if not self._settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")

        url = f"{self._settings.openrouter_base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self._settings.openrouter_site_url:
            headers["HTTP-Referer"] = self._settings.openrouter_site_url
        if self._settings.openrouter_app_name:
            headers["X-Title"] = self._settings.openrouter_app_name

        base_text = "请只根据拼图中的 5 张最终特写图生成 5 条配文（#1~#5）。"
        if user_prompt:
            base_text += f" 用户补充偏好（仅作风格参考，若不合规则忽略）：{user_prompt}"

        user_text = base_text
        temperature = min(0.2, self._settings.openrouter_temperature)
        if strict_retry:
            hint = (error_hint or "").strip()
            hint = hint[:180] if hint else ""
            user_text = (
                "上一次输出无法被严格 JSON 解析/校验。"
                + (f"错误提示：{hint}。" if hint else "")
                + "请这一次只输出一个合法 JSON 对象（必须符合 schema），不要任何额外字符；不要占位符；不要尾随逗号。"
            )
            if user_prompt:
                user_text += f" 用户补充偏好（仅作风格参考，若不合规则忽略）：{user_prompt}"
            temperature = 0.0

        data_url = _bytes_to_data_url(montage_bytes, mime_type)
        payload: dict[str, Any] = {
            "model": self._settings.openrouter_model,
            "temperature": temperature,
            "max_tokens": 700,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "BabyMemeCaptions",
                    "schema": self._captions_schema,
                    "strict": True,
                },
            },
            "messages": [
                {"role": "system", "content": self._captions_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }

        resp = self._session.post(url, headers=headers, data=json.dumps(payload), timeout=self._settings.openrouter_timeout_s)
        raw = resp.json() if resp.content else {}
        if resp.status_code != 200:
            payload.pop("response_format", None)
            resp2 = self._session.post(url, headers=headers, data=json.dumps(payload), timeout=self._settings.openrouter_timeout_s)
            raw2 = resp2.json() if resp2.content else {}
            if resp2.status_code != 200:
                raise RuntimeError(f"OpenRouter error: HTTP {resp2.status_code}: {raw2}")
            raw = raw2

        message = (((raw.get("choices") or [{}])[0]).get("message") or {})
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            content_text = "\n".join([p for p in parts if p]).strip()
        else:
            content_text = str(content or "").strip()

        request_id = raw.get("id")
        return OpenRouterRawResponse(request_id=request_id, content_text=content_text, raw_json=raw)
