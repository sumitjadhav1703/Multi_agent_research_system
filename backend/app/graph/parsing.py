"""Extract a single JSON object from a model completion."""
from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model output did not contain a JSON object.")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model output JSON must be an object.")
    return value
