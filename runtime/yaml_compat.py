"""Dependency-free YAML subset for repository contracts.

PyYAML is used when it is installed outside the repository.  The fallback is
limited to the mapping/list/scalar subset used by the frozen contracts and
installer manifest; it is deliberately not a general YAML implementation.
"""

from __future__ import annotations

import ast
import json
from typing import Any

try:  # pragma: no cover - exercised when PyYAML is installed
    import yaml as _yaml
except ImportError:  # pragma: no cover - minimal runtime path
    _yaml = None


def safe_load(text: str) -> Any:
    if _yaml is not None and hasattr(_yaml, "safe_load"):
        return _yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _parse_subset(text)


def _clean_lines(text: str) -> list[tuple[int, str]]:
    raw = []
    for line in text.splitlines():
        line = _strip_comment(line).rstrip()
        if line.strip():
            raw.append(line)
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(raw):
        line = raw[i]
        stripped = line.strip()
        while stripped.count("[") > stripped.count("]") and i + 1 < len(raw):
            i += 1
            stripped += " " + raw[i].strip()
        out.append((len(line) - len(line.lstrip(" ")), stripped))
        i += 1
    return out


def _strip_comment(line: str) -> str:
    quote = None
    escaped = False
    for i, char in enumerate(line):
        if char == "\\" and quote and not escaped:
            escaped = True
            continue
        if char in ("'", '"') and not escaped:
            quote = None if quote == char else char if quote is None else quote
        if char == "#" and quote is None and (i == 0 or line[i - 1].isspace()):
            return line[:i]
        escaped = False
    return line


def _key(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return str(ast.literal_eval(value))
    return value


def _scalar(value: str) -> Any:
    value = value.strip()
    if value in ("", "null", "Null", "NULL", "~"):
        return None
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return [_scalar(x) for x in value[1:-1].split(",") if x.strip()]
    if value.startswith("{") and value.endswith("}"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return ast.literal_eval(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _split_mapping(value: str) -> tuple[str, str] | None:
    quote = None
    for i, char in enumerate(value):
        if char in ("'", '"'):
            quote = None if quote == char else char if quote is None else quote
        if char == ":" and quote is None:
            return value[:i], value[i + 1:]
    return None


def _parse_subset(text: str) -> Any:
    lines = _clean_lines(text)

    def block(index: int, indent: int):
        if index >= len(lines):
            return {}, index
        is_list = lines[index][0] == indent and lines[index][1].startswith("-")
        result: Any = [] if is_list else {}
        while index < len(lines):
            current_indent, value = lines[index]
            if current_indent < indent or current_indent > indent:
                break
            if is_list:
                if not value.startswith("-"):
                    break
                item_text = value[1:].strip()
                index += 1
                mapping = _split_mapping(item_text)
                if mapping:
                    item: dict[str, Any] = {
                        _key(mapping[0]): _scalar(mapping[1]) if mapping[1].strip() else None
                    }
                    if not mapping[1].strip() and index < len(lines) and lines[index][0] > indent:
                        item[_key(mapping[0])], index = block(index, lines[index][0])
                    if index < len(lines) and lines[index][0] > indent:
                        extra, index = block(index, lines[index][0])
                        if isinstance(extra, dict):
                            item.update(extra)
                    result.append(item)
                elif item_text:
                    result.append(_scalar(item_text))
                elif index < len(lines) and lines[index][0] > indent:
                    child, index = block(index, lines[index][0])
                    result.append(child)
                else:
                    result.append(None)
            else:
                mapping = _split_mapping(value)
                if not mapping:
                    index += 1
                    continue
                key, raw_value = mapping
                index += 1
                if raw_value.strip():
                    result[_key(key)] = _scalar(raw_value)
                elif index < len(lines) and lines[index][0] > indent:
                    result[_key(key)], index = block(index, lines[index][0])
                else:
                    result[_key(key)] = {}
        return result, index

    parsed, _ = block(0, lines[0][0] if lines else 0)
    return parsed
