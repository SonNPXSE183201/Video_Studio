"""Mỗi bộ truyện là một dự án độc lập trong projects/<slug>/."""
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Tuple

from core.utils import read_json, read_yaml, slugify, write_json, write_yaml

SERIES_HEADER = """# ==========================================================================
# HỒ SƠ BỘ TRUYỆN - tool tự điền khi chạy lần đầu (genre/art_style: auto).
# Muốn đổi thể loại/phong cách: sửa giá trị rồi chạy lại `studio.py run`.
# Danh sách thể loại: python studio.py styles
# ==========================================================================
"""

DEFAULT_SERIES: Dict[str, Any] = {
    "title": "",
    "genre": "auto",
    "art_style": "auto",
    "setting_en": "",
    "era_en": "",
    "analysis_note": "",
    "voice": {
        "ref_audio": "assets/voices/default.wav",
        "ref_text": "assets/voices/default.txt",
    },
    "chapters_per_episode": 10,
    "watermark": "",
}

OVERRIDES_TEMPLATE = """# Sửa tay từng cảnh mà không cần UI. Ví dụ:
# chapters:
#   3:
#     scenes:
#       12:
#         subject_en: "a young man in a white shirt stands at a bus stop in the rain"
#         location_id: "tram_xe_buyt"
#         characters: ["lamphong"]
#         extra_en: "night, neon reflections"
#         motion: true          # ép tạo/không tạo chuyển động cho cảnh này
# Sau khi sửa: python studio.py redo <du_an> --ch 3 --scene 12 --stage image
chapters: {}
"""


def chapter_number(path: str, fallback: int) -> int:
    match = re.search(r"\d+", os.path.basename(path))
    return int(match.group()) if match else fallback


class Project:
    def __init__(self, projects_dir: str, name: str):
        self.slug = slugify(name)
        self.root = os.path.join(projects_dir, self.slug)
        self.chapters_dir = os.path.join(self.root, "chapters")
        self.bible_dir = os.path.join(self.root, "bible")
        self.refs_dir = os.path.join(self.root, "refs")
        self.work_dir = os.path.join(self.root, "work")
        self.output_dir = os.path.join(self.root, "output")
        self.logs_dir = os.path.join(self.root, "logs")
        self.cache_dir = os.path.join(self.work_dir, "_cache")
        self.series_path = os.path.join(self.root, "series.yaml")
        self.overrides_path = os.path.join(self.root, "overrides.yaml")
        self.characters_path = os.path.join(self.bible_dir, "characters.json")
        self.locations_path = os.path.join(self.bible_dir, "locations.json")
        self.glossary_path = os.path.join(self.bible_dir, "glossary.json")
        self.episodes_state_path = os.path.join(self.work_dir, "episodes.json")

    # ------------------------------------------------------------------ setup
    def exists(self) -> bool:
        return os.path.isdir(self.root)

    def create(self, title: str, import_from: Optional[str] = None) -> List[str]:
        for path in (
            self.chapters_dir,
            self.bible_dir,
            self.refs_dir,
            self.work_dir,
            self.output_dir,
            self.logs_dir,
            self.cache_dir,
        ):
            os.makedirs(path, exist_ok=True)
        if not os.path.exists(self.series_path):
            series = dict(DEFAULT_SERIES)
            series["title"] = title
            write_yaml(self.series_path, series, SERIES_HEADER)
        if not os.path.exists(self.overrides_path):
            with open(self.overrides_path, "w", encoding="utf-8") as handle:
                handle.write(OVERRIDES_TEMPLATE)
        if not os.path.exists(self.glossary_path):
            write_json(
                self.glossary_path,
                {
                    "_huong_dan": "Cách đọc riêng cho TTS. Ví dụ: \"Lv\": \"cấp\", \"VIP\": \"vi ai pi\"",
                },
            )
        imported: List[str] = []
        if import_from and os.path.isdir(import_from):
            for name in sorted(os.listdir(import_from)):
                src = os.path.join(import_from, name)
                if os.path.isfile(src) and name.lower().endswith(".txt"):
                    dst = os.path.join(self.chapters_dir, name)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                        imported.append(name)
        return imported

    def ensure_dirs(self) -> None:
        for path in (self.bible_dir, self.refs_dir, self.work_dir, self.output_dir, self.logs_dir, self.cache_dir):
            os.makedirs(path, exist_ok=True)

    # ---------------------------------------------------------------- series
    def load_series(self) -> Dict[str, Any]:
        data = read_yaml(self.series_path, {}) or {}
        merged = dict(DEFAULT_SERIES)
        merged.update(data)
        voice = dict(DEFAULT_SERIES["voice"])
        voice.update(data.get("voice") or {})
        merged["voice"] = voice
        return merged

    def save_series(self, series: Dict[str, Any]) -> None:
        write_yaml(self.series_path, series, SERIES_HEADER)

    def load_overrides(self) -> Dict[str, Any]:
        return read_yaml(self.overrides_path, {}) or {}

    def scene_override(self, chapter: int, scene_index: int) -> Dict[str, Any]:
        chapters = (self.load_overrides().get("chapters") or {})
        chapter_data = chapters.get(chapter) or chapters.get(str(chapter)) or {}
        scenes = chapter_data.get("scenes") or {}
        return scenes.get(scene_index) or scenes.get(str(scene_index)) or {}

    def load_glossary(self) -> Dict[str, str]:
        data = read_json(self.glossary_path, {}) or {}
        return {k: str(v) for k, v in data.items() if not k.startswith("_")}

    # -------------------------------------------------------------- chapters
    def chapter_files(self) -> List[Tuple[int, str]]:
        if not os.path.isdir(self.chapters_dir):
            return []
        files = [
            os.path.join(self.chapters_dir, f)
            for f in os.listdir(self.chapters_dir)
            if f.lower().endswith(".txt")
        ]
        numbered = [(chapter_number(p, i + 1), p) for i, p in enumerate(sorted(files))]
        numbered.sort(key=lambda item: (item[0], item[1]))
        return numbered

    def chapter_dir(self, chapter: int) -> str:
        path = os.path.join(self.work_dir, f"ch{chapter:04d}")
        for sub in ("images", "motion", "audio", "render"):
            os.makedirs(os.path.join(path, sub), exist_ok=True)
        return path

    def chapter_state_path(self, chapter: int) -> str:
        return os.path.join(self.chapter_dir(chapter), "state.json")

    def load_chapter_state(self, chapter: int) -> Dict[str, Any]:
        return read_json(self.chapter_state_path(chapter), {}) or {}

    def save_chapter_state(self, chapter: int, state: Dict[str, Any]) -> None:
        write_json(self.chapter_state_path(chapter), state)

    def chapter_video_path(self, chapter: int) -> str:
        return os.path.join(self.output_dir, "chapters", f"Chuong_{chapter:04d}.mp4")
