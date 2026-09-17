from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CASES_PATH = Path("presentation/demo_cases.json")


def load_demo_cases(path: str | Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    cases_path = Path(path)
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("demo cases payload must contain a non-empty cases list")
    for index, case in enumerate(cases):
        _validate_case(case, index)
    return {"cases": cases}


def _validate_case(case: Any, index: int) -> None:
    if not isinstance(case, dict):
        raise ValueError(f"case {index} must be an object")
    for key in ("id", "question"):
        _require_text(case, key, f"case {index}")
    if not isinstance(case.get("filters"), dict):
        raise ValueError(f"case {index} filters must be an object")


def _require_text(payload: dict[str, Any], key: str, path: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} {key} must be a non-empty string")
    return value
