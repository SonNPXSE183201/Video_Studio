"""Làm sạch chương truyện và chia thành chunk TTS kèm khoảng nghỉ theo dấu câu."""
import re
from typing import Any, Dict, List, Optional

from core.vi_normalizer import normalize_for_tts

CLOSERS = " \"”’»)]】」』"
QUOTE_OPENERS = ("“", '"', "「", "『", "‘", "'")

DEFAULT_PAUSES = {
    "comma": 150,
    "sentence": 300,
    "question": 380,
    "ellipsis": 520,
    "paragraph": 600,
    "dialogue": 680,
    "title": 1200,
}

TITLE_RE = re.compile(r"^\s*(chương|chapter|hồi|quyển|tiết)\s*[\dIVXLCivxlc]+", re.IGNORECASE)


def extract_standardization_table(raw_text: str) -> List[Dict[str, str]]:
    """Đọc bảng chuẩn hóa danh xưng ở cuối chương (nếu có) làm gợi ý cho Bible."""
    keyword = "Bảng chuẩn hóa danh xưng"
    if keyword not in raw_text:
        return []
    items = []
    for line in raw_text.split(keyword)[-1].strip().split("\n"):
        line = line.strip().lstrip("-*•").strip()
        if ":" in line:
            name, desc = (part.strip() for part in line.split(":", 1))
            if name and len(name) < 50:
                items.append({"name": name, "description": desc})
    return items


def clean_paragraphs(raw_text: str) -> List[str]:
    """Trả về danh sách đoạn văn hiển thị (giữ ngoặc kép để làm phụ đề)."""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    for keyword in (
        "Bảng chuẩn hóa danh xưng nhân vật & địa danh trong chương:",
        "Bảng chuẩn hóa danh xưng",
        "--- HẾT CHƯƠNG ---",
    ):
        if keyword in text:
            text = text.split(keyword)[0]

    paragraphs: List[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in {"***", "* * *", "---"}:
            continue
        if re.match(r"^(NGUYÊN TÁC|Thời gian|Tác giả|Nguồn|Converter|Editor)\s*:", stripped, re.IGNORECASE):
            continue
        line = re.sub(r"[·•・]", "", stripped)            # c·hết -> chết
        line = re.sub(r"(?:\.\s*){3,}|…+", "…", line)
        line = re.sub(r"\s*…\s*", "… ", line).strip()
        line = re.sub(r"[ \t　]+", " ", line)
        line = re.sub(r"([,:;!?])(?=[^\s\d”\"’)\]】」』…])", r"\1 ", line)
        line = re.sub(r"(?<!\d)\.(?=[^\s\d”\"’)\]】」』….])", ". ", line)
        line = re.sub(r"\s+([,.:;!?])", r"\1", line)
        if line:
            paragraphs.append(line)
    return paragraphs


def split_sentences(paragraph: str) -> List[str]:
    parts = re.split(r"(?<=[.!?…])([\"”’»)\]】」』]*)\s+", paragraph)
    sentences: List[str] = []
    buffer = ""
    for index, part in enumerate(parts):
        if index % 2 == 0:
            buffer += part
        else:
            buffer += part
            if buffer.strip():
                sentences.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        sentences.append(buffer.strip())
    return sentences


def _split_long(sentence: str, max_chars: int) -> List[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    clauses = [c.strip() for c in re.split(r"(?<=[,;:])\s+", sentence) if c.strip()]
    pieces: List[str] = []
    current = ""
    for clause in clauses:
        if len(clause) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            words = clause.split()
            chunk = ""
            for word in words:
                if chunk and len(chunk) + 1 + len(word) > max_chars:
                    pieces.append(chunk)
                    chunk = word
                else:
                    chunk = f"{chunk} {word}".strip()
            if chunk:
                pieces.append(chunk)
            continue
        if current and len(current) + 1 + len(clause) > max_chars:
            pieces.append(current)
            current = clause
        else:
            current = f"{current} {clause}".strip()
    if current:
        pieces.append(current)
    return pieces


def end_pause_kind(text: str) -> str:
    stripped = text.rstrip(CLOSERS)
    if stripped.endswith("…") or stripped.endswith("..."):
        return "ellipsis"
    last = stripped[-1:] if stripped else ""
    if last in "?!":
        return "question"
    if last in ",;:":
        return "comma"
    return "sentence"


def is_dialogue(paragraph: str) -> bool:
    return paragraph.lstrip().startswith(QUOTE_OPENERS) or paragraph.rstrip().endswith(("”", '"'))


def build_chunks(
    paragraphs: List[str],
    max_chars: int = 160,
    merge_sentences: bool = True,
    pauses: Optional[Dict[str, int]] = None,
    glossary: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Chia đoạn văn thành chunk TTS ngắn, mỗi chunk biết khoảng nghỉ phía sau."""
    pause_table = dict(DEFAULT_PAUSES)
    pause_table.update(pauses or {})
    chunks: List[Dict[str, Any]] = []
    dialogue_flags = [is_dialogue(p) for p in paragraphs]

    for p_index, paragraph in enumerate(paragraphs):
        is_title = p_index == 0 and bool(TITLE_RE.match(paragraph))
        pieces: List[str] = []
        for sentence in split_sentences(paragraph):
            pieces.extend(_split_long(sentence, max_chars))

        merged: List[str] = []
        for piece in pieces:
            if (
                merge_sentences
                and merged
                and not is_title
                and len(merged[-1]) + 1 + len(piece) <= max_chars
            ):
                merged[-1] = f"{merged[-1]} {piece}"
            else:
                merged.append(piece)

        para_chunks: List[Dict[str, Any]] = []
        for piece in merged:
            tts_text = normalize_for_tts(piece, glossary)
            if end_pause_kind(piece) == "comma":
                # Giữ ngữ điệu lửng khi câu còn tiếp ở chunk sau.
                tts_text = re.sub(r"[.,;:]$", "", tts_text) + ","
            if not re.search(r"\w", tts_text):
                # Đoạn chỉ có "……" / ký hiệu: không đọc, biến thành nhịp nghỉ.
                target = para_chunks[-1] if para_chunks else (chunks[-1] if chunks else None)
                if target is not None:
                    target["pause_after_ms"] = max(
                        target["pause_after_ms"], pause_table["paragraph"] + pause_table["ellipsis"]
                    )
                continue
            para_chunks.append(
                {
                    "id": len(chunks) + len(para_chunks),
                    "para": p_index,
                    "display": piece,
                    "tts": tts_text,
                    "pause_after_ms": pause_table[end_pause_kind(piece)],
                    "is_title": is_title,
                    "dialogue": dialogue_flags[p_index],
                }
            )

        if para_chunks:
            last = para_chunks[-1]
            next_dialogue = dialogue_flags[p_index + 1] if p_index + 1 < len(paragraphs) else False
            boundary = pause_table["paragraph"]
            if dialogue_flags[p_index] or next_dialogue:
                boundary = max(boundary, pause_table["dialogue"])
            if is_title:
                boundary = pause_table["title"]
            last["pause_after_ms"] = max(last["pause_after_ms"], boundary)
        chunks.extend(para_chunks)

    for index, chunk in enumerate(chunks):
        chunk["id"] = index
    if chunks:
        chunks[-1]["pause_after_ms"] = max(chunks[-1]["pause_after_ms"], 800)
    return chunks


def chapter_title(paragraphs: List[str]) -> str:
    if paragraphs and TITLE_RE.match(paragraphs[0]):
        return paragraphs[0]
    return ""
