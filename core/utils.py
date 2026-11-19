"""Tiện ích dùng chung: log, JSON/YAML an toàn, fingerprint, slug, font."""
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from typing import Any, Iterable, List, Optional, Set

import yaml

_LOG_HANDLE = None


def set_log_file(path: Optional[str]) -> None:
    global _LOG_HANDLE
    if _LOG_HANDLE:
        _LOG_HANDLE.close()
        _LOG_HANDLE = None
    if path:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        _LOG_HANDLE = open(path, "a", encoding="utf-8")


def log(message: str, tag: str = "") -> None:
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}]{'[' + tag + ']' if tag else ''} {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
        sys.stdout.flush()
    if _LOG_HANDLE:
        _LOG_HANDLE.write(line + "\n")
        _LOG_HANDLE.flush()


def fingerprint(*parts: Any) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def file_fingerprint(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def read_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        log(f"Không đọc được {path}: {exc}", "Cảnh báo")
        return default


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_yaml(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return default if data is None else data


def write_yaml(path: str, data: Any, header: str = "") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        if header:
            handle.write(header.rstrip() + "\n")
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, width=110)
    os.replace(tmp, path)


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def slugify(name: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).replace("đ", "d").replace("Đ", "D")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return (text or "project")[:max_len]


def parse_range(spec: Optional[str]) -> Optional[Set[int]]:
    """'1-5,8,10-12' -> {1,2,3,4,5,8,10,11,12}; None -> None (tất cả)."""
    if not spec:
        return None
    result: Set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            result.update(range(int(start), int(end) + 1))
        else:
            result.add(int(part))
    return result


def first_existing(paths: Iterable[str]) -> Optional[str]:
    for path in paths:
        if path and os.path.exists(path):
            return path
    return None


def find_font(bold: bool = True) -> Optional[str]:
    """Tìm font TTF có đủ dấu tiếng Việt cho PIL/drawtext."""
    project_fonts = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
    candidates: List[str] = []
    if os.path.isdir(project_fonts):
        candidates += [
            os.path.join(project_fonts, f)
            for f in sorted(os.listdir(project_fonts))
            if f.lower().endswith((".ttf", ".otf"))
        ]
    if bold:
        candidates += [
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    found = first_existing(candidates)
    if found:
        return found
    fc_match = shutil.which("fc-match")
    if fc_match:
        import subprocess

        res = subprocess.run(
            [fc_match, "-f", "%{file}", "Noto Sans:bold" if bold else "Noto Sans"],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and os.path.exists(res.stdout.strip()):
            return res.stdout.strip()
    return None


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
