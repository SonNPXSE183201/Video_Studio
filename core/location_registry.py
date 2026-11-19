"""Location Bible: mỗi địa điểm có mô tả hình ảnh cố định để bối cảnh nhất quán."""
import os
from typing import Any, Dict, List, Optional

from core.character_registry import CharacterRegistry
from core.utils import read_json, write_json


class LocationRegistry:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.locations: Dict[str, Dict[str, Any]] = read_json(filepath, {}) or {}
        self.alias_map: Dict[str, str] = {}
        self._rebuild()

    _norm = staticmethod(CharacterRegistry._normalise)

    def _rebuild(self) -> None:
        self.alias_map = {}
        for loc_id, data in self.locations.items():
            for name in [data.get("name", ""), *data.get("aliases", [])]:
                key = self._norm(name)
                if key and key not in self.alias_map:
                    self.alias_map[key] = loc_id

    def save(self) -> None:
        write_json(self.filepath, self.locations)

    def resolve(self, value: Any) -> Optional[str]:
        if not value:
            return None
        raw = str(value).strip()
        if raw in self.locations:
            return raw
        return self.alias_map.get(self._norm(raw))

    def upsert(self, profile: Dict[str, Any], chapter: int) -> Optional[str]:
        name = str(profile.get("name") or "").strip()
        description = str(profile.get("description_en") or "").strip()
        if not name:
            return None
        loc_id = self.resolve(profile.get("id")) or self.resolve(name)
        if not loc_id:
            base = CharacterRegistry.make_character_id(name) or "location"
            loc_id, suffix = base, 2
            while loc_id in self.locations:
                loc_id, suffix = f"{base}{suffix}", suffix + 1
            self.locations[loc_id] = {
                "name": name,
                "aliases": [],
                "description_en": "",
                "first_seen_chapter": chapter,
            }
        record = self.locations[loc_id]
        for alias in profile.get("aliases", []) or []:
            alias = str(alias).strip()
            if alias and alias != record["name"] and alias not in record["aliases"]:
                record["aliases"].append(alias)
        # Mô tả đã ổn định thì giữ nguyên để bối cảnh không trôi giữa các chương.
        if description and len(record.get("description_en", "")) < 20:
            record["description_en"] = description
        record["last_seen_chapter"] = chapter
        self._rebuild()
        return loc_id

    def description(self, loc_id: Optional[str]) -> str:
        if not loc_id or loc_id not in self.locations:
            return ""
        return str(self.locations[loc_id].get("description_en", "")).strip()

    def build_llm_context(self, max_items: int = 60) -> str:
        ordered = sorted(
            self.locations.items(),
            key=lambda item: -(item[1].get("last_seen_chapter") or 0),
        )[:max_items]
        return "\n".join(
            f"- id={loc_id}; name={d.get('name')}; aliases={', '.join(d.get('aliases', [])) or 'none'}; "
            f"look={d.get('description_en') or 'not established'}"
            for loc_id, d in ordered
        )
