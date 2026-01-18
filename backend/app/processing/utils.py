from __future__ import annotations

import json
import re
from typing import Any


_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _try_loads(s: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def extract_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        raise ValueError("empty model response")

    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\\s*```$", "", candidate)
        candidate = candidate.strip()

    parsed = _try_loads(candidate)
    if parsed is not None:
        return parsed

    # Common repair: remove trailing commas.
    repaired = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    parsed = _try_loads(repaired)
    if parsed is not None:
        return parsed

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in model response")

    sliced = candidate[start : end + 1]
    parsed = _try_loads(sliced)
    if parsed is not None:
        return parsed
    repaired = _TRAILING_COMMA_RE.sub(r"\1", sliced)
    parsed = _try_loads(repaired)
    if parsed is not None:
        return parsed
    raise ValueError("invalid JSON after extraction/repair")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
