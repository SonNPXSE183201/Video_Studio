"""Storyboard (bảng ảnh các cảnh), thumbnail và báo cáo chương để duyệt không cần UI."""
import os
import textwrap
from typing import Any, Dict, List, Optional

from core.utils import find_font, format_duration
from core.subtitle import display_safe


def _font(size: int, bold: bool = True):
    from PIL import ImageFont

    path = find_font(bold)
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def contact_sheet(scenes: List[Dict[str, Any]], out_path: str, columns: int = 5, thumb_w: int = 384) -> Optional[str]:
    from PIL import Image, ImageDraw

    items = [s for s in scenes if s.get("image") and os.path.exists(s["image"])]
    if not items:
        return None
    thumb_h = int(thumb_w * 9 / 16)
    caption_h = 92
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + caption_h)), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    title_font, text_font = _font(20), _font(15, bold=False)
    for index, scene in enumerate(items):
        x = (index % columns) * thumb_w
        y = (index // columns) * (thumb_h + caption_h)
        with Image.open(scene["image"]) as img:
            img = img.convert("RGB")
            img.thumbnail((thumb_w, thumb_h))
            sheet.paste(img, (x + (thumb_w - img.width) // 2, y))
        flags = []
        if scene.get("clip"):
            flags.append("MOTION")
        if scene.get("qa_failed"):
            flags.append("QA!")
        if scene.get("fallback"):
            flags.append("LLM?")
        label = f"#{scene['index']}  {scene.get('duration', 0):.1f}s  {' '.join(flags)}"
        draw.text((x + 8, y + thumb_h + 4), label, fill=(255, 210, 80), font=title_font)
        caption = textwrap.shorten(display_safe(scene.get("text", "")), width=110, placeholder="…")
        for line_no, line in enumerate(textwrap.wrap(caption, width=48)[:3]):
            draw.text((x + 8, y + thumb_h + 30 + line_no * 19), line, fill=(220, 220, 220), font=text_font)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    sheet.save(out_path, "JPEG", quality=85)
    return out_path


def thumbnail(image_path: str, title: str, out_path: str, size=(1280, 720)) -> Optional[str]:
    from PIL import Image, ImageDraw, ImageFilter

    if not image_path or not os.path.exists(image_path):
        return None
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        ratio = max(size[0] / img.width, size[1] / img.height)
        img = img.resize((int(img.width * ratio) + 1, int(img.height * ratio) + 1))
        left, top = (img.width - size[0]) // 2, (img.height - size[1]) // 2
        canvas = img.crop((left, top, left + size[0], top + size[1]))
    shade = Image.new("L", size, 0)
    shade_draw = ImageDraw.Draw(shade)
    for y in range(size[1] // 2, size[1]):
        shade_draw.line([(0, y), (size[0], y)], fill=int(200 * (y - size[1] / 2) / (size[1] / 2)))
    canvas = Image.composite(Image.new("RGB", size, (0, 0, 0)), canvas, shade.filter(ImageFilter.GaussianBlur(4)))
    draw = ImageDraw.Draw(canvas)
    font = _font(72)
    lines = textwrap.wrap(display_safe(title), width=26)[:2]
    y = size[1] - 60 - len(lines) * 86
    for line in lines:
        draw.text((60, y), line, font=font, fill=(255, 214, 64), stroke_width=5, stroke_fill=(0, 0, 0))
        y += 86
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    canvas.save(out_path, "JPEG", quality=90)
    return out_path


def write_report(path: str, chapter: int, title: str, timeline: Dict[str, Any], scenes: List[Dict[str, Any]], notes: List[str]) -> str:
    lines = [
        f"# Báo cáo chương {chapter}: {title}",
        "",
        f"- Thời lượng: {format_duration(timeline.get('total_duration_sec', 0))}",
        f"- Số cảnh: {len(scenes)} (có chuyển động: {sum(1 for s in scenes if s.get('clip'))})",
        f"- Cảnh LLM lỗi (dùng dự phòng): {[s['index'] for s in scenes if s.get('fallback')] or 'không'}",
        f"- Cảnh ảnh không qua QA sau khi vẽ lại: {[s['index'] for s in scenes if s.get('qa_failed')] or 'không'}",
        "",
        "## Giọng đọc cần nghe lại",
    ]
    warnings = timeline.get("warnings") or []
    if warnings:
        for item in warnings:
            lines.append(f"- chunk {item['id']} (CER={item.get('cer')}): {item['text']}  →  ASR nghe: {item.get('asr')}")
    else:
        lines.append("- Không có.")
    lines += ["", "## Ảnh cần xem lại"]
    flagged = [s for s in scenes if s.get("qa_failed")]
    if flagged:
        for scene in flagged:
            lines.append(f"- cảnh {scene['index']}: {', '.join(scene.get('qa_reasons', []))}")
        lines.append("")
        lines.append("Sửa bằng overrides.yaml rồi: `python studio.py redo <du_an> --ch N --scene K --stage image`")
    else:
        lines.append("- Không có.")
    if notes:
        lines += ["", "## Ghi chú", *[f"- {n}" for n in notes]]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path
