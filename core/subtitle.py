"""Sinh phụ đề ASS: câu ngắn tối đa 2 dòng, thời gian chia theo số ký tự."""
import os
import re
from typing import Any, Dict, List


def _ass_time(ms: float) -> str:
    cs = int(round(ms / 10.0))
    hours, cs = divmod(cs, 360000)
    minutes, cs = divmod(cs, 6000)
    seconds, cs = divmod(cs, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


# Font phụ đề Latin (Noto Sans...) không có glyph CJK: 【】 hiện thành ô vuông (thấy trên pod thật).
_DISPLAY_MAP = str.maketrans({
    "【": "[", "】": "]", "〖": "[", "〗": "]", "「": "“", "」": "”", "『": "“", "』": "”",
    "《": "«", "》": "»", "〈": "‹", "〉": "›", "（": "(", "）": ")", "：": ":", "，": ",",
    "。": ".", "！": "!", "？": "?", "；": ";", "～": "~", "　": " ",
})


def display_safe(text: str) -> str:
    return (text or "").translate(_DISPLAY_MAP)


def _escape(text: str) -> str:
    text = display_safe(text).replace("\\", "/").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text).strip()


def split_caption(text: str, max_chars: int) -> List[str]:
    """Tách câu dài thành các đoạn <= max_chars, ưu tiên ngắt ở dấu câu."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    parts = [p for p in re.split(r"(?<=[,;:.!?…])\s+", text) if p]
    segments: List[str] = []
    current = ""
    for part in parts:
        if len(part) > max_chars:
            if current:
                segments.append(current)
                current = ""
            words = part.split()
            buf = ""
            for word in words:
                if buf and len(buf) + 1 + len(word) > max_chars:
                    segments.append(buf)
                    buf = word
                else:
                    buf = f"{buf} {word}".strip()
            current = buf
            continue
        if current and len(current) + 1 + len(part) > max_chars:
            segments.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        segments.append(current)
    return segments


def wrap_two_lines(text: str, line_chars: int) -> str:
    if len(text) <= line_chars:
        return text
    middle = len(text) // 2
    spaces = [m.start() for m in re.finditer(" ", text)]
    if not spaces:
        return text
    cut = min(spaces, key=lambda pos: abs(pos - middle))
    return text[:cut] + r"\N" + text[cut + 1 :]


class SubtitleGenerator:
    def __init__(self, cfg: Dict[str, Any], resolution=(1920, 1080)):
        self.cfg = cfg
        # Cỡ chữ/lề luôn tính theo hệ 1920x1080; libass tự co giãn theo video thật,
        # nên đổi độ phân giải xuất không làm phụ đề to/nhỏ bất thường.
        self.res_x, self.res_y = 1920, 1080

    def generate(self, timeline: Dict[str, Any], output_path: str) -> str:
        c = self.cfg
        line_chars = int(c.get("max_chars_per_line", 42))
        max_lines = int(c.get("max_lines", 2))
        header = f"""[Script Info]
Title: AI Video Studio
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {self.res_x}
PlayResY: {self.res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{c.get('font_name', 'Noto Sans')},{c.get('font_size', 52)},{c.get('primary_color', '&H0000FFFF')},&H000000FF,{c.get('outline_color', '&H00000000')},&H80000000,-1,0,0,0,100,100,0,0,1,{c.get('outline_width', 3)},{c.get('shadow', 1)},2,80,80,{c.get('margin_v', 60)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines: List[str] = []
        for chunk in timeline.get("chunks", []):
            text = _escape(chunk.get("display", ""))
            if not text:
                continue
            segments = split_caption(text, line_chars * max_lines)
            start, end = float(chunk["start_ms"]), float(chunk["end_ms"])
            total_chars = sum(len(s) for s in segments) or 1
            cursor = start
            for index, segment in enumerate(segments):
                share = (end - start) * len(segment) / total_chars
                seg_end = end if index == len(segments) - 1 else cursor + share
                lines.append(
                    f"Dialogue: 0,{_ass_time(cursor)},{_ass_time(seg_end)},Default,,0,0,0,,"
                    f"{wrap_two_lines(segment, line_chars)}"
                )
                cursor = seg_end
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(header + "\n".join(lines) + "\n")
        return output_path
