"""Tự nhận diện thể loại, thời đại, phong cách vẽ của bộ truyện từ vài chương đầu."""
import re
from typing import Any, Dict, List, Tuple

from core.ollama_client import OllamaClient
from core.style import list_art_styles, list_styles, load_style
from core.utils import log

KEYWORD_RULES: List[Tuple[str, str]] = [
    (r"tang thi|zombie|xác sống|mạt thế|tận thế", "mat_the"),
    (r"tinh hạm|cơ giáp|vũ trụ|phi thuyền|võng du|thực tế ảo", "khoa_huyen"),
    (r"lệ quỷ|quỷ dị|trừ tà|âm phủ|linh dị|oán hồn|quái đàm", "linh_di"),
    (r"luyện khí|trúc cơ|kim đan|nguyên anh|linh thạch|tu tiên|tu chân|tông môn|phi kiếm", "tien_hiep"),
    (r"đấu khí|võ hồn|ma thú|đấu giả|huyết mạch|đại lục", "huyen_huyen"),
    (r"bệ hạ|hoàng thượng|triều đình|nương nương|phủ đệ|thái giám|quan phủ", "lich_su_co_dai"),
    (r"máy nhắn tin|đại ca đại|199\d|xuống biển|nhà máy quốc doanh|tem phiếu", "do_thi_tq_1990s"),
    (r"quán net|nokia|200\d|olympic", "do_thi_tq_2000s"),
    (r"wechat|weibo|201[0-5]|tàu điện ngầm", "do_thi_tq_2010s"),
    (r"điện thoại|công ty|tổng tài|đại học|xe hơi|livestream", "do_thi_hien_dai"),
]


def heuristic_genre(text: str) -> str:
    lowered = text.casefold()
    scores: Dict[str, int] = {}
    for pattern, genre in KEYWORD_RULES:
        hits = len(re.findall(pattern, lowered))
        if hits:
            scores[genre] = scores.get(genre, 0) + hits
    if not scores:
        return "do_thi_hien_dai"
    return max(scores.items(), key=lambda item: item[1])[0]


def analyze_series(ollama: OllamaClient, samples: List[str], title: str = "") -> Dict[str, Any]:
    styles = list_styles()
    style_ids = [s[0] for s in styles]
    art_ids = list(list_art_styles().keys())
    catalog = "\n".join(f"- {sid}: {name}. {desc}" for sid, name, desc in styles)
    joined = "\n\n---\n\n".join(samples)
    system = (
        "You are a story analyst for a Vietnamese web-novel video studio. Read the Vietnamese "
        "chapters (often translated Chinese web novels) and classify the world so that every "
        "illustration matches the right genre, country and era. Return strict JSON only."
    )
    prompt = (
        f"TITLE: {title}\n\nGENRE PRESETS:\n{catalog}\n\nART STYLES: {', '.join(art_ids)}\n\n"
        f"CHAPTER SAMPLES:\n{joined}\n\n"
        "Pick exactly one genre id from GENRE PRESETS. For Chinese urban stories choose the "
        "decade preset from explicit clues (technology, years, prices, events); if unclear use "
        "do_thi_hien_dai. Return:\n"
        '{"genre":"preset_id","era_en":"e.g. mainland China, 1996","setting_en":"one sentence: '
        'country, era, world type, main places","art_style":"art style id or auto",'
        '"reason_vi":"giải thích ngắn bằng tiếng Việt"}'
    )
    result = ollama.generate_json(prompt, system_prompt=system) or {}
    genre = str(result.get("genre", "")).strip()
    fallback = heuristic_genre(joined)
    if genre not in style_ids:
        log(f"LLM không chọn được thể loại hợp lệ ('{genre}'), dùng heuristic: {fallback}", "Phân tích")
        genre = fallback
    art = str(result.get("art_style", "auto")).strip()
    if art not in art_ids:
        art = load_style(genre).get("default_art_style", "cinematic_realistic")
    return {
        "genre": genre,
        "art_style": art,
        "era_en": str(result.get("era_en", "")).strip(),
        "setting_en": str(result.get("setting_en", "")).strip(),
        "analysis_note": str(result.get("reason_vi", "")).strip() or f"heuristic={fallback}",
    }
