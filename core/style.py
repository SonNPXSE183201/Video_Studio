"""Nạp preset thể loại (config/styles/*.yaml) và phong cách vẽ (config/art_styles.yaml)."""
import os
from typing import Any, Dict, List, Tuple

from core.utils import deep_merge, read_yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STYLES_DIR = os.path.join(ROOT, "config", "styles")
ART_STYLES_PATH = os.path.join(ROOT, "config", "art_styles.yaml")


def list_styles() -> List[Tuple[str, str, str]]:
    result = []
    for name in sorted(os.listdir(STYLES_DIR)):
        if name.endswith(".yaml") and not name.startswith("_"):
            style_id = name[:-5]
            data = read_yaml(os.path.join(STYLES_DIR, name), {}) or {}
            result.append((style_id, str(data.get("name", style_id)), str(data.get("description", "")).strip()))
    return result


def load_style(style_id: str, _depth: int = 0) -> Dict[str, Any]:
    path = os.path.join(STYLES_DIR, f"{style_id}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không có preset thể loại '{style_id}' ({path})")
    data = read_yaml(path, {}) or {}
    parent = data.pop("extends", None)
    if parent and _depth < 5:
        data = deep_merge(load_style(parent, _depth + 1), data)
    data["id"] = style_id
    return data


def list_art_styles() -> Dict[str, Dict[str, Any]]:
    return read_yaml(ART_STYLES_PATH, {}) or {}


def load_art_style(name: str) -> Dict[str, Any]:
    styles = list_art_styles()
    if name not in styles:
        raise KeyError(f"Không có phong cách vẽ '{name}'. Có: {', '.join(styles)}")
    data = dict(styles[name])
    data["id"] = name
    return data
