"""Extract a single JSON object from a model completion."""
from __future__ import annotations

import json
import re


def parse_json_object(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start >= 0:
        try:
            value, _end = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            start = raw.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = raw.find("{", start + 1)
    raise ValueError("Model output did not contain a JSON object.")
