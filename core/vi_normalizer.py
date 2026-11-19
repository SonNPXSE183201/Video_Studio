"""Chuẩn hóa văn bản tiếng Việt thành dạng đọc được cho TTS.

Phụ đề vẫn dùng văn bản gốc; chỉ chuỗi gửi vào OmniVoice đi qua module này.
Mục tiêu: không còn ký hiệu/số/chữ viết tắt khiến model vấp hoặc đọc sượt.
"""
import re
import unicodedata
from typing import Dict, List, Optional

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

# Cách đọc mặc định; glossary.json của từng dự án được ưu tiên hơn.
DEFAULT_GLOSSARY: Dict[str, str] = {
    "VIP": "vi ai pi",
    "CEO": "xi i âu",
    "KTV": "ca tê vê",
    "OK": "ô kê",
    "Ok": "ô kê",
    "ok": "ô kê",
    "QQ": "qui qui",
    "PK": "pê ca",
    "BOSS": "bót",
    "Boss": "bót",
    "boss": "bót",
    "HP": "hát pê",
    "MP": "em pê",
    "EXP": "kinh nghiệm",
    "NPC": "en pê xê",
    "GPS": "gi pi ét",
    "TV": "ti vi",
    "USB": "u ét bê",
    "MV": "em vê",
    "WC": "vê kép xê",
    "IQ": "ai kiu",
    "EQ": "i kiu",
    "DNA": "đê en a",
    "CPU": "xê pê u",
    "AI": "ây ai",
    # Từ mượn tiếng Anh hay gặp trong truyện hệ thống/đô thị (test thật: "hack" bị đọc thành "hát"/"hắc").
    "hack": "hách",
    "Hack": "Hách",
    "hacker": "hách cơ",
    "Hacker": "Hách cơ",
    "game": "ghêm",
    "Game": "Ghêm",
    "online": "on lai",
    "level": "le vồ",
    "Level": "Le vồ",
    "buff": "bấp",
    "skill": "xkin",
    "Skill": "Xkin",
    "app": "áp",
    "email": "i meo",
    "laptop": "láp tóp",
    "livestream": "lai xtrim",
}

UNITS = {
    "km/h": "ki lô mét trên giờ",
    "km": "ki lô mét",
    "kg": "ki lô gam",
    "cm": "xen ti mét",
    "mm": "mi li mét",
    "m2": "mét vuông",
    "m²": "mét vuông",
    "m3": "mét khối",
    "ml": "mi li lít",
    "°C": "độ xê",
    "℃": "độ xê",
    "h": "giờ",
}

CURRENCY_BEFORE = {"$": "đô la", "¥": "tệ", "￥": "tệ", "€": "ơ rô", "£": "bảng"}


def _read_triple(n: int, full: bool) -> List[str]:
    hundreds, tens, units = n // 100, (n // 10) % 10, n % 10
    words: List[str] = []
    if hundreds > 0 or full:
        words += [DIGITS[hundreds], "trăm"]
    if tens == 0:
        if units > 0:
            if hundreds > 0 or full:
                words.append("linh")
            words.append(DIGITS[units])
    elif tens == 1:
        words.append("mười")
        if units == 5:
            words.append("lăm")
        elif units > 0:
            words.append(DIGITS[units])
    else:
        words += [DIGITS[tens], "mươi"]
        if units == 1:
            words.append("mốt")
        elif units == 4:
            words.append("tư")
        elif units == 5:
            words.append("lăm")
        elif units > 0:
            words.append(DIGITS[units])
    return words


def _below_billion(n: int, full: bool) -> str:
    groups = [(n // 1_000_000) % 1000, (n // 1000) % 1000, n % 1000]
    names = ["triệu", "nghìn", ""]
    words: List[str] = []
    started = False
    for group, name in zip(groups, names):
        if group == 0:
            continue
        words += _read_triple(group, full=started or full)
        if name:
            words.append(name)
        started = True
    return " ".join(words)


def number_to_words(n: int) -> str:
    if n < 0:
        return "âm " + number_to_words(-n)
    if n == 0:
        return "không"
    if n >= 1_000_000_000:
        high, rest = divmod(n, 1_000_000_000)
        text = number_to_words(high) + " tỷ"
        if rest:
            text += " " + _below_billion(rest, full=True)
        return text
    return _below_billion(n, full=False)


def _digits_one_by_one(text: str) -> str:
    return " ".join(DIGITS[int(d)] for d in text if d.isdigit())


def read_number_token(token: str) -> str:
    """Đọc một chuỗi số: '1.000' -> một nghìn, '3,5' -> ba phẩy năm."""
    token = token.strip()
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return number_to_words(int(re.sub(r"[.,]", "", token)))
    match = re.fullmatch(r"(\d+)[.,](\d+)", token)
    if match:
        whole, frac = match.groups()
        frac_text = _digits_one_by_one(frac) if frac.startswith("0") or len(frac) > 3 else number_to_words(int(frac))
        return f"{read_number_token(whole)} phẩy {frac_text}"
    digits = re.sub(r"\D", "", token)
    if not digits:
        return token
    if len(digits) > 15 or (digits.startswith("0") and len(digits) > 1):
        return _digits_one_by_one(digits)
    return number_to_words(int(digits))


NUMBER = r"\d+(?:[.,]\d+)*"


def _apply_glossary(text: str, glossary: Dict[str, str]) -> str:
    # Khóa dài trước để "km/h" thắng "km".
    for key in sorted(glossary, key=len, reverse=True):
        value = glossary[key]
        if not key:
            continue
        if re.fullmatch(r"[\w\s]+", key):
            text = re.sub(rf"(?<!\w){re.escape(key)}(?!\w)", value, text)
        else:
            text = text.replace(key, value)
    return text


def normalize_for_tts(text: str, glossary: Optional[Dict[str, str]] = None) -> str:
    text = unicodedata.normalize("NFC", text or "")
    merged = dict(DEFAULT_GLOSSARY)
    merged.update(glossary or {})
    text = _apply_glossary(text, merged)

    # Ngoặc trang trí / bảng hệ thống -> ngắt hơi bằng dấu phẩy.
    text = re.sub(r"[【\[「『〔]\s*", ", ", text)
    text = re.sub(r"\s*[】\]」』〕]", ", ", text)
    text = re.sub(r"[《》〈〉<>]", "", text)
    text = re.sub(r"\s*[()（）]\s*", ", ", text)
    text = re.sub(r"[“”\"'‘’«»]", "", text)
    text = re.sub(r"\s*[—–]+\s*", ", ", text)
    text = text.replace("→", " thành ").replace("⇒", " thành ")
    text = text.replace("&", " và ")

    # Cấp độ: Lv1, LV.2, lv 10 -> cấp một...
    text = re.sub(
        rf"(?i)(?<!\w)lv\.?\s*({NUMBER})",
        lambda m: f"cấp {read_number_token(m.group(1))}",
        text,
    )
    text = re.sub(r"(?i)(?<!\w)lv(?!\w)", "cấp", text)

    # Tiền tệ đứng trước số.
    for symbol, word in CURRENCY_BEFORE.items():
        text = re.sub(
            rf"{re.escape(symbol)}\s*({NUMBER})",
            lambda m, w=word: f"{read_number_token(m.group(1))} {w}",
            text,
        )

    # Phần trăm, nhân, cộng, trừ.
    text = re.sub(
        rf"(?<![\w])\+\s*({NUMBER})\s*%",
        lambda m: f" tăng {read_number_token(m.group(1))} phần trăm",
        text,
    )
    text = re.sub(rf"({NUMBER})\s*%", lambda m: f"{read_number_token(m.group(1))} phần trăm", text)
    text = re.sub(rf"(?:×|(?<![A-Za-z])[xX])\s*({NUMBER})(?!\w)",lambda m: f" nhân {read_number_token(m.group(1))}", text)
    text = re.sub(rf"(?<![\w])\+\s*({NUMBER})", lambda m: f" cộng {read_number_token(m.group(1))}", text)
    text = re.sub(rf"(?<=\s)-\s*({NUMBER})", lambda m: f"trừ {read_number_token(m.group(1))}", text)

    # Giờ phút 10:30 và khoảng 3-5 / 3~5.
    text = re.sub(
        r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)",
        lambda m: f"{number_to_words(int(m.group(1)))} giờ {number_to_words(int(m.group(2)))}",
        text,
    )
    text = re.sub(
        rf"({NUMBER})\s*[-~～]\s*({NUMBER})",
        lambda m: f"{read_number_token(m.group(1))} đến {read_number_token(m.group(2))}",
        text,
    )

    # Đơn vị sau số.
    for unit in sorted(UNITS, key=len, reverse=True):
        text = re.sub(
            rf"({NUMBER})\s*{re.escape(unit)}(?![A-Za-z0-9])",
            lambda m, u=unit: f"{read_number_token(m.group(1))} {UNITS[u]}",
            text,
        )

    # Mọi số còn lại (tách số dính chữ: "box2" -> "box 2").
    text = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", text)
    text = re.sub(NUMBER, lambda m: read_number_token(m.group(0)), text)

    # Dọn ký hiệu còn sót (giữ chữ, số, dấu câu cơ bản).
    text = text.replace("…", "...")
    text = re.sub(r"\.{2,}", "…", text)
    text = re.sub(r"[^\w\s.,!?;:…]", " ", text)
    text = re.sub(r"\s+([.,!?;:…])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)
    text = re.sub(r"([.!?…])\s*,", r"\1", text)
    text = re.sub(r"^[\s,;:.]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r",$", ".", text)
    return text


def speakable_length(text: str) -> int:
    """Số ký tự chữ thực sự được đọc (dùng để ước lượng tốc độ đọc)."""
    return len(re.sub(r"[^\w]", "", text or ""))
