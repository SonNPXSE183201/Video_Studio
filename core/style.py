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


THEMES_DIR = os.path.join(ROOT, "config", "themes")
TEXT_FIELDS = ("director_rules_en", "props_en", "location_rules_en", "character_rules_en")


def list_themes() -> List[Tuple[str, str, str]]:
    if not os.path.isdir(THEMES_DIR):
        return []
    result = []
    for name in sorted(os.listdir(THEMES_DIR)):
        if name.endswith(".yaml"):
            data = read_yaml(os.path.join(THEMES_DIR, name), {}) or {}
            result.append((name[:-5], str(data.get("name", name[:-5])), str(data.get("description", "")).strip()))
    return result


def apply_themes(style: Dict[str, Any], themes: List[str]) -> Dict[str, Any]:
    """Cộng dồn chủ đề (kinh doanh, quan trường, đấu trí...) lên preset thể loại.

    Chủ đề chỉ bổ sung luật/đạo cụ/guard; thời đại và thế giới vẫn do thể loại quyết định.
    """
    merged = dict(style)
    applied = []
    for theme_id in themes or []:
        path = os.path.join(THEMES_DIR, f"{theme_id}.yaml")
        if not os.path.exists(path):
            continue
        theme = read_yaml(path, {}) or {}
        for field in TEXT_FIELDS:
            if theme.get(field):
                merged[field] = f"{merged.get(field, '')} {theme[field]}".strip()
        if theme.get("negative"):
            merged["negative"] = ", ".join(p for p in (merged.get("negative", ""), theme["negative"]) if p)
        if theme.get("context_guards"):
            merged["context_guards"] = list(merged.get("context_guards") or []) + list(theme["context_guards"])
        applied.append(theme_id)
    merged["themes"] = applied
    return merged


def _range_contains(key: Any, number: int) -> bool:
    text = str(key).strip()
    if "-" in text:
        start, end = text.split("-", 1)
        return int(start or 0) <= number <= int(end or 10**9)
    return text.isdigit() and int(text) == number


def genre_for_chapter(series: Dict[str, Any], number: int) -> str:
    """series.genre_by_chapter: {"1-150": do_thi_tq_1990s, "151-": do_thi_tq_2000s}."""
    for key, genre in (series.get("genre_by_chapter") or {}).items():
        try:
            if _range_contains(key, number):
                return str(genre)
        except ValueError:
            continue
    return str(series.get("genre"))


def detect_era_genre(text: str, current_genre: str) -> Tuple[str, Dict[str, int]]:
    """Đếm các năm được nhắc (năm 1998, 2003...) và tìm preset có khoảng năm khớp nhất.

    Trả về (preset gợi ý hoặc "" nếu không đủ chứng cứ, {preset: số lần}).
    """
    import re

    years = [int(y) for y in re.findall(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)", text)]
    if not years:
        return "", {}
    current = load_style(current_genre) if current_genre else {}
    if not current.get("years"):
        return "", {}  # chỉ áp dụng cho nhóm preset có mốc năm (đô thị)
    counts: Dict[str, int] = {}
    for style_id, _, _ in list_styles():
        span = load_style(style_id).get("years")
        if span:
            hits = sum(1 for y in years if span[0] <= y <= span[1])
            if hits:
                counts[style_id] = hits
    if not counts:
        return "", counts
    best = max(counts.items(), key=lambda item: item[1])
    if best[0] != current_genre and best[1] >= 2 and best[1] > counts.get(current_genre, 0) * 2:
        return best[0], counts
    return "", counts


def list_art_styles() -> Dict[str, Dict[str, Any]]:
    return read_yaml(ART_STYLES_PATH, {}) or {}


def load_art_style(name: str) -> Dict[str, Any]:
    styles = list_art_styles()
    if name not in styles:
        raise KeyError(f"Không có phong cách vẽ '{name}'. Có: {', '.join(styles)}")
    data = dict(styles[name])
    data["id"] = name
    return data
